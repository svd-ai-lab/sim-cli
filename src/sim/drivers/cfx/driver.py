"""CFX driver for sim.

Ansys CFX is a commercial CFD solver. Execution is via command-line tools:
  - Definition files (.def): ``cfx5solve -batch -def <file>``
  - CCL overrides (.ccl):    ``cfx5solve -batch -def <def> -ccl <ccl>``
  - Post-processing (.cse):  ``cfx5post -batch <session> <results>``

Persistent session mode uses ``cfx5post -line <results.res>`` for interactive
post-processing. The agent sends CCL fragments via ``enterccl`` + ``.e``, and
queries quantities via Perl ``evaluate()`` — e.g. ``areaAve(Pressure)@inlet``.

Three-phase workflow:
  Phase 1: cfx5solve -batch -def <file>       → solve (non-interactive)
  Phase 2: cfx5post -line <results.res>       → interactive post-processing
  Phase 3: agent sends CCL/Perl via run()     → quantitative feedback per step
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import queue
from datetime import datetime, timezone
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, RunResult, SolverInstall

log = logging.getLogger(__name__)

# CFX cfx5post -line emits "ERROR" / "INTERNAL" / "WARNING" lines on stdout.
# stderr is rarely populated (cfx5post buffers everything via its own log).
_CFX_STDOUT_RULES: list[dict] = [
    {"pattern": r"^\s*ERROR\b", "severity": "error",
     "code": "cfx.post.error"},
    {"pattern": r"\bINTERNAL\b", "severity": "error",
     "code": "cfx.post.internal_error"},
    {"pattern": r"License checkout failed", "severity": "error",
     "code": "cfx.license.checkout_failed"},
]


def _default_cfx_probes(enable_gui: bool = False) -> list:
    """CFX probe list — generic_probes() + cfx5post-specific channels.

    Generic (via generic_probes()):
      #1  ProcessMetaProbe      #1+ RuntimeTimeoutProbe
      #3  StdoutJsonTailProbe   #3+ PythonTracebackProbe   #9 WorkdirDiffProbe

    CFX-specific:
      #6  TextStreamRulesProbe(cfx:stdout) — ERROR / INTERNAL / license
      #5  DomainExceptionMapProbe — post-processor

    NOT wired:
      #2  stderr — cfx5post -line keeps stderr empty
      #4  SdkAttributeProbe — session.summary already exposes state
      #7  log file — solver log lives next to .res, not a per-snippet log
      #8  GUI — cfx5post -line is text-only; no window to probe
    """
    from sim.inspect import (                                            # noqa: PLC0415
        DomainExceptionMapProbe, GuiDialogProbe, ScreenshotProbe,
        TextStreamRulesProbe, generic_probes,
    )
    _g = {p.name: p for p in generic_probes()}
    probes: list = [
        _g["process-meta"],                                              # #1
        _g["runtime-timeout"],                                           # #1+
        TextStreamRulesProbe(                                            # #6
            source="cfx:stdout",
            text_selector=lambda ctx: ctx.stdout,
            rules=_CFX_STDOUT_RULES,
        ),
        _g["stdout-json-tail"],                                          # #3
        _g["python-traceback"],                                          # #3+
        DomainExceptionMapProbe(),                                        # #5
    ]
    if enable_gui:
        probes.append(GuiDialogProbe(                                    # #8a
            process_name_substrings=("cfx5", "ansys"),
            code_prefix="cfx.gui"))
        probes.append(ScreenshotProbe(                                   # #8b
            filename_prefix="cfx_shot",
            process_name_substrings=("cfx5", "ansys")))
    probes.append(_g["workdir-diff"])                                    # #9
    return probes


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

_CCL_SECTION_RE = re.compile(
    r"^\s*(FLOW|DOMAIN|LIBRARY|COMMAND FILE|OUTPUT CONTROL|SOLVER CONTROL)\s*:",
    re.MULTILINE,
)

_CCL_VERSION_RE = re.compile(r"Version\s*=\s*([\d.]+)")


def _version_from_awp_key(key: str) -> str | None:
    """Extract version from AWP_ROOT241 → '24.1', AWP_ROOT252 → '25.2'."""
    m = re.search(r"(\d{2,3})$", key)
    if not m:
        return None
    digits = m.group(1)
    if len(digits) == 3:
        return f"{digits[0:2]}.{digits[2]}"
    elif len(digits) == 2:
        return f"{digits[0]}.{digits[1]}"
    return None


def _version_from_path(p: Path) -> str | None:
    """Extract version from path like .../v241/... → '24.1'."""
    for part in p.parts:
        m = re.match(r"v(\d{3})$", part)
        if m:
            d = m.group(1)
            return f"{d[0:2]}.{d[2]}"
    return None


# ---------------------------------------------------------------------------
# Install-dir finders (strategy chain)
# ---------------------------------------------------------------------------


def _candidates_from_env() -> list[tuple[Path, str]]:
    """Check AWP_ROOT* environment variables for CFX installations."""
    out: list[tuple[Path, str]] = []
    for key, val in os.environ.items():
        if key.startswith("AWP_ROOT") and val:
            cfx_bin = Path(val) / "CFX" / "bin"
            if cfx_bin.is_dir():
                out.append((cfx_bin, f"env:{key}"))
    return out


def _candidates_from_path() -> list[tuple[Path, str]]:
    """``which cfx5solve`` — PATH probe."""
    out: list[tuple[Path, str]] = []
    cfx5solve = shutil.which("cfx5solve") or shutil.which("cfx5solve.exe")
    if cfx5solve:
        p = Path(cfx5solve).resolve().parent
        out.append((p, "which:cfx5solve"))
    return out


def _candidates_from_defaults() -> list[tuple[Path, str]]:
    """Scan standard Ansys install directories."""
    bases: list[Path] = []
    for drive in ("C", "D", "E"):
        bases.append(Path(f"{drive}:/Program Files/ANSYS Inc"))
        bases.append(Path(f"{drive}:/Program Files (x86)/ANSYS Inc"))
    # Linux
    bases.extend([Path("/usr/local/ansys"), Path("/ansys_inc")])

    out: list[tuple[Path, str]] = []
    for base in bases:
        if not base.is_dir():
            continue
        try:
            for candidate in sorted(base.iterdir(), reverse=True):
                cfx_bin = candidate / "CFX" / "bin"
                if cfx_bin.is_dir():
                    out.append((cfx_bin, f"default-path:{cfx_bin}"))
        except PermissionError:
            continue
    return out


_INSTALL_FINDERS = [
    _candidates_from_env,
    _candidates_from_path,
    _candidates_from_defaults,
]


def _scan_cfx_installs() -> list[SolverInstall]:
    """Find every CFX installation on this host. Pure stdlib."""
    found: dict[str, SolverInstall] = {}

    for finder in _INSTALL_FINDERS:
        try:
            candidates = finder()
        except Exception:
            continue
        for bin_dir, source in candidates:
            # Look for cfx5solve executable
            cfx5solve = bin_dir / "cfx5solve.exe"
            if not cfx5solve.is_file():
                cfx5solve = bin_dir / "cfx5solve"
                if not cfx5solve.is_file():
                    continue

            key = str(cfx5solve.resolve())
            if key in found:
                continue

            # Extract version
            version = None
            if "env:" in source:
                env_key = source.split(":")[1]
                version = _version_from_awp_key(env_key)
            if not version:
                version = _version_from_path(bin_dir)
            if not version:
                version = "unknown"

            found[key] = SolverInstall(
                name="cfx",
                version=version,
                path=str(bin_dir),
                source=source,
                extra={"cfx5solve": str(cfx5solve)},
            )

    return sorted(found.values(), key=lambda i: i.version, reverse=True)


# ---------------------------------------------------------------------------
# Error detection patterns
# ---------------------------------------------------------------------------

_CFX_ERROR_PATTERNS = [
    re.compile(r"\bFATAL\b", re.IGNORECASE),
    re.compile(r"\bERROR\b"),  # Case-sensitive: CFX uses uppercase ERROR
    re.compile(r"An error has occurred", re.IGNORECASE),
    re.compile(r"License .* not available", re.IGNORECASE),
    re.compile(r"license .* denied", re.IGNORECASE),
    re.compile(r"Unable to start", re.IGNORECASE),
    re.compile(r"Cannot open", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------


class _CfxPostSession:
    """Manages a live ``cfx5post -line`` subprocess for interactive queries.

    Protocol discovered via empirical testing:
    - ``e`` enters CCL input mode; ``.e`` submits, ``.c`` cancels
    - ``s [<name>]`` returns object state (list of paths)
    - ``! <perl>`` executes Perl; ``evaluate('expr'@'loc')`` returns values
    - ``>action`` (inside enterccl) executes CCL actions (print, export, ...)
    - ``calc <func>, <args>`` runs built-in calculator (values in progress bar)
    - ``q`` quits
    """

    def __init__(self, cfx5post: str, res_file: str):
        self._proc = subprocess.Popen(
            [cfx5post, "-line", res_file],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,
        )
        self._out_q: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        # Wait until CFX is idle: poll until 2s of stdout silence, max 60s.
        # CFX emits a burst of output while loading the result file; when it
        # stops, the process is ready for commands.
        _deadline = time.monotonic() + 60.0
        while time.monotonic() < _deadline:
            chunk = self._drain(timeout=2.0)
            if not chunk:
                break  # 2s silence → CFX ready
        else:
            self._drain()  # drain any remaining output on timeout

    def _read_stdout(self):
        assert self._proc.stdout is not None
        for line in iter(self._proc.stdout.readline, ""):
            self._out_q.put(line)

    def _drain(self, timeout: float = 0.5) -> list[str]:
        """Drain all available lines from stdout."""
        lines: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                lines.append(self._out_q.get(timeout=0.1).rstrip())
            except queue.Empty:
                if lines:
                    break
        return lines

    def send_command(self, cmd: str, wait: float = 5.0) -> list[str]:
        """Send a single-line command (h, s, calc, !, q) and read response."""
        assert self._proc.stdin is not None
        self._proc.stdin.write(cmd + "\n")
        self._proc.stdin.flush()
        time.sleep(wait)
        return self._drain()

    def send_ccl(self, ccl: str, wait: float = 5.0) -> list[str]:
        """Enter CCL mode, send a CCL block, submit with ``.e``."""
        assert self._proc.stdin is not None
        self._proc.stdin.write("e\n")
        self._proc.stdin.flush()
        time.sleep(1)
        self._drain()  # clear "When done..." prompt

        for line in ccl.strip().splitlines():
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        time.sleep(0.5)

        self._proc.stdin.write(".e\n")
        self._proc.stdin.flush()
        time.sleep(wait)
        return self._drain()

    def evaluate(self, expression: str, location: str, wait: float = 5.0) -> tuple[float | None, str]:
        """Evaluate a CEL expression at a location via Perl.

        Returns (value, units) or (None, error_message).
        Uses chr(64) for @ to avoid Perl array interpolation.
        """
        # Build Perl command with single quotes only (no double-quote issues)
        perl = (
            f"! ($v,$u) = evaluate('{expression}'.chr(64).'{location}');"
            " print 'RESULT: '.$v.' ['.$u.']'.chr(10);"
        )
        lines = self.send_command(perl, wait=wait)
        for line in lines:
            m = re.search(r"RESULT:\s*([-\d.eE+]+)\s*\[(.+?)\]", line)
            if m:
                return float(m.group(1)), m.group(2)
        return None, f"No RESULT in output: {lines}"

    def quit(self):
        """Send quit and kill the process."""
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.write("quit\n")
                self._proc.stdin.flush()
                time.sleep(2)
        except (BrokenPipeError, OSError):
            pass
        try:
            self._proc.kill()
            self._proc.wait(timeout=5)
        except Exception:
            pass

    @property
    def alive(self) -> bool:
        return self._proc.poll() is None


class CfxDriver:
    """Sim driver for Ansys CFX.

    DriverProtocol surface:
        name, detect, lint, connect, parse_output, run_file, detect_installed

    Session surface (supports_session=True):
        launch, run, query, disconnect

    Session architecture (three-phase):
        1. launch(def_file=...) → cfx5solve -batch (solve) → cfx5post -line (interactive)
        2. run(code) → send CCL or Perl to cfx5post -line → get feedback
        3. disconnect() → quit cfx5post, clean up
    """

    def __init__(self):
        self._session: _CfxPostSession | None = None
        self._session_info: dict = {}
        self._ccl_history: list[str] = []  # CCL blocks sent via enterccl
        self.probes: list = _default_cfx_probes(enable_gui=False)
        self._sim_dir = Path.cwd() / ".sim"

    @property
    def name(self) -> str:
        return "cfx"

    @property
    def supports_session(self) -> bool:
        return True

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self._session.alive

    # -- detect ---------------------------------------------------------------

    def detect(self, script: Path) -> bool:
        """Detect CFX files: .def, .cfx, or .ccl with CCL sections."""
        try:
            ext = script.suffix.lower()

            if ext == ".def":
                return script.is_file()

            if ext == ".cfx":
                return script.is_file()

            if ext == ".ccl":
                if not script.is_file():
                    return False
                text = script.read_text(encoding="utf-8", errors="replace")
                return bool(_CCL_SECTION_RE.search(text))

        except (OSError, UnicodeDecodeError):
            pass
        return False

    # -- lint -----------------------------------------------------------------

    def lint(self, script: Path) -> LintResult:
        """Validate a CFX file."""
        diagnostics: list[Diagnostic] = []
        ext = script.suffix.lower()

        if ext == ".def":
            return self._lint_def(script, diagnostics)
        elif ext == ".ccl":
            return self._lint_ccl(script, diagnostics)
        elif ext == ".cfx":
            return self._lint_def(script, diagnostics)  # same binary check
        else:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {ext} (expected .ccl, .def, or .cfx)",
                )
            )
            return LintResult(ok=False, diagnostics=diagnostics)

    def _lint_def(self, script: Path, diagnostics: list[Diagnostic]) -> LintResult:
        """Lint a binary .def or .cfx file — existence and size check only."""
        if not script.exists():
            diagnostics.append(Diagnostic(level="error", message=f"File not found: {script}"))
        elif script.stat().st_size < 100:
            diagnostics.append(
                Diagnostic(level="warning", message="Definition file is suspiciously small")
            )
        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def _lint_ccl(self, script: Path, diagnostics: list[Diagnostic]) -> LintResult:
        """Lint a CCL text file."""
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            diagnostics.append(Diagnostic(level="error", message=f"Cannot read file: {e}"))
            return LintResult(ok=False, diagnostics=diagnostics)

        # Check for FLOW section
        if not re.search(r"^\s*FLOW\s*:", text, re.MULTILINE):
            diagnostics.append(
                Diagnostic(level="warning", message="No FLOW section found — CCL may be incomplete")
            )

        # Check COMMAND FILE version
        ver_match = _CCL_VERSION_RE.search(text)
        if ver_match:
            diagnostics.append(Diagnostic(level="info", message=f"CCL version: {ver_match.group(1)}"))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    # -- connect / detect_installed -------------------------------------------

    def connect(self) -> ConnectionInfo:
        """Lightweight availability check via detect_installed."""
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="cfx",
                version=None,
                status="not_installed",
                message="No Ansys CFX installation detected on this host",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="cfx",
            version=top.version,
            status="ok",
            message=f"CFX {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Scan for CFX installations. Pure stdlib, no SDK import."""
        return _scan_cfx_installs()

    # -- parse_output ---------------------------------------------------------

    def parse_output(self, stdout: str) -> dict:
        """Extract structured results from CFX solver output.

        Priority: last JSON line on stdout (driver convention), then
        CFX-specific patterns (iteration count, wall clock time).
        """
        if not stdout or not stdout.strip():
            return {}

        # Try standard JSON convention first (scan from bottom)
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

        # Parse CFX-specific output patterns
        result: dict = {}

        # Iteration count
        iters = re.findall(r"OUTER LOOP ITERATION\s*=\s*(\d+)", stdout)
        if iters:
            result["iterations"] = int(iters[-1])

        # Wall clock time
        time_match = re.search(r"Total wall clock time:\s*([\d.]+)\s*s", stdout)
        if time_match:
            result["wall_clock_s"] = float(time_match.group(1))

        # Final residuals
        residuals = re.findall(
            r"(U-Mom|V-Mom|W-Mom|P-Mass|E-Engy|K-TurbKE|O-TurbFreq)\s+"
            r"[\d.eE+-]+\s+([\d.eE+-]+)",
            stdout,
        )
        if residuals:
            result["final_residuals"] = {
                name: float(val) for name, val in residuals[-7:]
            }

        return result

    # -- run_file -------------------------------------------------------------

    def run_file(self, script: Path) -> RunResult:
        """Execute a CFX simulation.

        - .def: ``cfx5solve -batch -def <file>``
        - .ccl: ``cfx5solve -batch -def <matching.def> -ccl <file>``
        """
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Ansys CFX is not installed on this host")

        cfx5solve = installs[0].extra.get("cfx5solve", "cfx5solve")
        work_dir = script.parent
        ext = script.suffix.lower()

        if ext == ".def":
            cmd = [cfx5solve, "-batch", "-def", str(script)]
        elif ext == ".ccl":
            def_file = self._find_def_for_ccl(script)
            if def_file is None:
                return RunResult(
                    exit_code=1,
                    stdout="",
                    stderr="No .def file found alongside .ccl — cannot solve without mesh",
                    duration_s=0,
                    script=str(script),
                    solver=self.name,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    errors=["No .def file found to apply CCL overrides to"],
                )
            cmd = [cfx5solve, "-batch", "-def", str(def_file), "-ccl", str(script)]
        elif ext == ".cfx":
            return RunResult(
                exit_code=1,
                stdout="",
                stderr=".cfx project files not directly executable; extract .def first with cfx5cmds",
                duration_s=0,
                script=str(script),
                solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
                errors=[".cfx project files not directly executable"],
            )
        else:
            return RunResult(
                exit_code=1,
                stdout="",
                stderr=f"Unsupported file type: {ext}",
                duration_s=0,
                script=str(script),
                solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
                errors=[f"Unsupported file type: {ext}"],
            )

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(work_dir),
                timeout=3600,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return RunResult(
                exit_code=-1,
                stdout="",
                stderr="CFX execution timed out after 3600s",
                duration_s=round(duration, 3),
                script=str(script),
                solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
                errors=["Execution timed out"],
            )

        duration = time.monotonic() - start
        stdout = proc.stdout.strip() if proc.stdout else ""
        stderr = proc.stderr.strip() if proc.stderr else ""

        # Error detection
        errors: list[str] = []
        combined = stdout + "\n" + stderr
        for pattern in _CFX_ERROR_PATTERNS:
            match = pattern.search(combined)
            if match:
                errors.append(f"[output] {match.group(0)}")

        exit_code = proc.returncode
        if exit_code == 0 and errors:
            exit_code = 1

        return RunResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_s=round(duration, 3),
            script=str(script),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            errors=errors,
        )

    # -- session lifecycle ----------------------------------------------------

    def launch(self, **kwargs) -> dict:
        """Start a CFX session: solve a .def file, then open cfx5post -line.

        Required kwargs:
            def_file (str|Path): path to .def file to solve

        Optional kwargs:
            skip_solve (bool): if True, skip solving and go straight to post
                               (requires existing .res file)
            res_file (str|Path): explicit .res file to load (skips solve)
        """
        if self._session is not None:
            raise RuntimeError("CFX session already active — disconnect first")

        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Ansys CFX is not installed on this host")

        bin_dir = Path(installs[0].path)
        cfx5solve = str(bin_dir / "cfx5solve.exe")
        cfx5post = str(bin_dir / "cfx5post.exe")
        if not Path(cfx5post).is_file():
            cfx5post = str(bin_dir / "cfx5post")

        res_file = kwargs.get("res_file")
        skip_solve = kwargs.get("skip_solve", False)

        if res_file:
            res_path = Path(res_file)
            skip_solve = True
        else:
            def_file = kwargs.get("def_file")
            if not def_file:
                raise RuntimeError("launch() requires def_file= or res_file=")
            def_path = Path(def_file)
            if not def_path.is_file():
                raise RuntimeError(f"Definition file not found: {def_path}")

            if not skip_solve:
                # Phase 1: Solve
                log.info("CFX session: solving %s", def_path)
                solve_result = self.run_file(def_path)
                if not solve_result.ok:
                    return {
                        "ok": False,
                        "error": f"Solve failed: {solve_result.errors}",
                        "solve_result": solve_result.to_dict(),
                    }
                self._session_info["solve_result"] = solve_result.to_dict()

            # Find the .res file produced by the solve
            work_dir = def_path.parent
            res_files = sorted(work_dir.glob(f"{def_path.stem}_*.res"))
            if not res_files:
                return {"ok": False, "error": "No .res file produced by solve"}
            res_path = res_files[-1]  # highest run number

        # Phase 2: Start cfx5post -line
        log.info("CFX session: starting cfx5post -line with %s", res_path)
        self._session = _CfxPostSession(cfx5post, str(res_path))
        self._session_info.update({
            "ok": True,
            "session_id": f"cfx-{id(self._session)}",
            "res_file": str(res_path),
            "mode": "post",
            "solver": "cfx",
            "version": installs[0].version,
        })
        return dict(self._session_info)

    def run(self, code: str, label: str = "") -> dict:
        """Execute a snippet inside the live cfx5post session and attach diagnostics.

        Wraps :meth:`_dispatch` with timing, an :class:`InspectCtx`, and the
        configured probe list. The shape of the returned dict matches
        ``_dispatch`` plus ``diagnostics`` and ``artifacts`` lists.
        """
        from sim.inspect import InspectCtx, collect_diagnostics         # noqa: PLC0415

        wd = self._sim_dir
        try:
            wd.mkdir(parents=True, exist_ok=True)
            before = sorted(
                str(p.relative_to(wd)).replace("\\", "/")
                for p in wd.rglob("*") if p.is_file()
            )
        except Exception:
            before = []

        t0 = time.monotonic()
        result = self._dispatch(code, label)
        wall = time.monotonic() - t0

        ctx = InspectCtx(
            stdout=result.get("stdout", "") or "",
            stderr=result.get("error", "") or "",
            workdir=str(wd),
            wall_time_s=wall,
            exit_code=0 if result.get("ok") else 1,
            driver_name=self.name,
            session_ns={"_result": result.get("result")},
            workdir_before=before,
        )
        diags, arts = collect_diagnostics(self.probes, ctx)
        result["diagnostics"] = [d.to_dict() for d in diags]
        result["artifacts"] = [a.to_dict() for a in arts]
        return result

    def _dispatch(self, code: str, label: str = "") -> dict:
        """Execute a command in the live cfx5post session.

        The ``code`` can be:
        - CCL block (starts with a CCL keyword like CONTOUR:, HARDCOPY:, etc.)
          → sent via enterccl + .e
        - Perl command (starts with ``!``)
          → sent as-is via send_command
        - ``evaluate(expr@loc)`` shorthand
          → parsed and executed via Perl evaluate()
        - Session command (s, d, calc, h, q)
          → sent as-is

        Returns dict with ``ok``, ``stdout`` (cleaned lines), and optional
        ``result`` (for evaluate).
        """
        if self._session is None or not self._session.alive:
            raise RuntimeError("No active CFX session — call launch() first")

        code = code.strip()
        result: dict = {"ok": True, "label": label}

        # Route 1: evaluate() shorthand
        eval_match = re.match(
            r"evaluate\(\s*['\"]?(.+?)['\"]?\s*@\s*['\"]?(.+?)['\"]?\s*\)",
            code,
        )
        if eval_match:
            expr, loc = eval_match.group(1), eval_match.group(2)
            value, units = self._session.evaluate(expr, loc)
            if value is not None:
                result["result"] = {"value": value, "units": units}
                result["stdout"] = f"{expr}@{loc} = {value} [{units}]"
            else:
                result["ok"] = False
                result["error"] = units  # error message stored in units
                result["stdout"] = units
            return result

        # Route 2: Perl command
        if code.startswith("!"):
            lines = self._session.send_command(code)
            result["stdout"] = self._clean_output(lines)
            if any("ERROR" in l for l in lines):
                result["ok"] = False
                result["error"] = result["stdout"]
            return result

        # Route 3: HARDCOPY with >print → hybrid batch rendering
        # cfx5post -line cannot render filled surfaces; delegate to -batch
        if "HARDCOPY:" in code and ">print" in code:
            return self._render_via_batch(code, label)

        # Route 3b: CCL block (enterccl)
        ccl_keywords = (
            "CONTOUR:", "PLANE:", "VECTOR:", "STREAMLINE:",
            "ISOSURFACE:", "CHART:", "EXPORT:", "CALCULATOR:", "DATA READER:",
            "VIEW:", "LIBRARY:", "FLOW:", "DOMAIN:", "BOUNDARY:",
            "EXPRESSION EVALUATOR:", ">",
        )
        if any(code.lstrip().startswith(kw) for kw in ccl_keywords):
            lines = self._session.send_ccl(code)
            result["stdout"] = self._clean_output(lines)
            if any("ERROR" in l or "INTERNAL" in l for l in lines):
                result["ok"] = False
                result["error"] = result["stdout"]
            else:
                self._ccl_history.append(code)
            return result

        # Route 4: Session command (s, d, calc, h)
        lines = self._session.send_command(code)
        result["stdout"] = self._clean_output(lines)
        return result

    def query(self, name: str) -> dict:
        """Query session state.

        Supported queries:
        - ``session.summary`` → session info + available objects
        - ``session.objects`` → list all CFX objects in the loaded results
        - ``session.variables`` → list available scalar/vector variables
        - ``session.boundaries`` → list boundary names
        - ``<expr>@<loc>`` → evaluate expression at location
        """
        if self._session is None or not self._session.alive:
            return {"ok": False, "error": "No active session"}

        if name == "session.summary":
            return {
                "ok": True,
                **self._session_info,
                "alive": self._session.alive,
            }

        if name == "session.objects":
            lines = self._session.send_command("s")
            objects = [
                l.strip() for l in lines
                if l.strip().startswith("/") and "/SYSTEM" not in l
            ]
            return {"ok": True, "objects": objects}

        if name == "session.variables":
            lines = self._session.send_command("s")
            variables = [
                l.strip().replace("/SCALAR VARIABLE:", "").replace("/VECTOR VARIABLE:", "")
                for l in lines
                if "/SCALAR VARIABLE:" in l or "/VECTOR VARIABLE:" in l
            ]
            return {"ok": True, "variables": variables}

        if name == "session.boundaries":
            lines = self._session.send_command("s")
            boundaries = [
                l.strip().split("BOUNDARY:")[-1]
                for l in lines
                if "/BOUNDARY:" in l
            ]
            return {"ok": True, "boundaries": boundaries}

        # Evaluate expression
        if "@" in name:
            expr, loc = name.rsplit("@", 1)
            value, units = self._session.evaluate(expr.strip(), loc.strip())
            if value is not None:
                return {"ok": True, "value": value, "units": units}
            return {"ok": False, "error": units}

        return {"ok": False, "error": f"Unknown query: {name}"}

    def disconnect(self, **kwargs) -> dict:
        """Tear down the cfx5post session."""
        if self._session is not None:
            self._session.quit()
            self._session = None
        self._session_info = {}
        self._ccl_history = []
        return {"ok": True, "disconnected": True}

    @staticmethod
    def _clean_output(lines: list[str]) -> str:
        """Strip progress bars and noise from cfx5post output."""
        cleaned = []
        for l in lines:
            s = l.strip()
            if not s:
                continue
            # Skip progress bars
            if "....|" in s or s.startswith("=") and len(s) > 2 and s == "=" * len(s):
                continue
            # Skip processing/completing noise
            if s in ("Processing...", "Completing...", "Processing CCL...",
                     "Processing action..."):
                continue
            if s.startswith("CFX>"):
                continue
            if s.startswith("0..."):
                continue
            cleaned.append(s)
        return "\n".join(cleaned)

    def _render_via_batch(self, code: str, label: str) -> dict:
        """Render an image using cfx5post -batch (hybrid mode).

        cfx5post -line cannot render filled contour surfaces. This method
        replays the CCL history (contour definitions etc.) into a temporary
        .cse file, appends the HARDCOPY block, and invokes cfx5post -batch
        for proper rendering with filled colors.
        """
        result: dict = {"ok": True, "label": label}
        res_file = self._session_info.get("res_file")
        if not res_file:
            result["ok"] = False
            result["error"] = "No res_file in session info"
            return result

        installs = self.detect_installed()
        if not installs:
            result["ok"] = False
            result["error"] = "CFX not installed"
            return result

        bin_dir = Path(installs[0].path)
        cfx5post = bin_dir / "cfx5post.exe"
        if not cfx5post.is_file():
            cfx5post = bin_dir / "cfx5post"

        # Build .cse: replay CCL history + HARDCOPY block
        cse_parts = list(self._ccl_history)  # contour defs, view changes, etc.
        cse_parts.append("WIREFRAME: Wireframe\n  Visibility = Off\nEND")
        cse_parts.append(code)  # HARDCOPY + >print

        cse_content = "\n\n".join(cse_parts)
        cse_dir = Path(res_file).parent
        cse_path = cse_dir / "_sim_render.cse"
        cse_path.write_text(cse_content, encoding="utf-8")

        try:
            proc = subprocess.run(
                [str(cfx5post), "-batch", str(cse_path), res_file],
                capture_output=True, text=True, timeout=120,
                cwd=str(cse_dir),
            )
            if proc.returncode != 0:
                result["ok"] = False
                result["error"] = (proc.stderr or proc.stdout or "").strip()

            img_match = re.search(r"Hardcopy Filename\s*=\s*(.+)", code)
            if img_match:
                img_path = Path(img_match.group(1).strip())
                if img_path.is_file():
                    result["image"] = str(img_path)
                    result["image_size"] = img_path.stat().st_size
                    result["stdout"] = f"Image exported: {img_path.name} ({result['image_size']} bytes)"
                else:
                    result["ok"] = False
                    result["error"] = f"Image not created: {img_path}"
        except subprocess.TimeoutExpired:
            result["ok"] = False
            result["error"] = "Batch rendering timed out"
        finally:
            cse_path.unlink(missing_ok=True)

        return result

    # -- helpers --------------------------------------------------------------

    def _find_def_for_ccl(self, ccl_file: Path) -> Path | None:
        """Find a .def file to pair with a .ccl file.

        Strategy: same stem first, then any .def in the same directory.
        """
        same_stem = ccl_file.with_suffix(".def")
        if same_stem.is_file():
            return same_stem
        defs = list(ccl_file.parent.glob("*.def"))
        return defs[0] if defs else None

    def post_process(self, res_file: Path, session_file: Path) -> RunResult:
        """Run CFD-Post in batch mode: ``cfx5post -batch <session> <results>``."""
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("Ansys CFX is not installed on this host")

        bin_dir = Path(installs[0].path)
        cfx5post = bin_dir / "cfx5post.exe"
        if not cfx5post.is_file():
            cfx5post = bin_dir / "cfx5post"

        cmd = [str(cfx5post), "-batch", str(session_file), str(res_file)]

        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(res_file.parent),
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return RunResult(
                exit_code=-1, stdout="", stderr="CFX-Post timed out after 600s",
                duration_s=round(duration, 3), script=str(session_file),
                solver=self.name, timestamp=datetime.now(timezone.utc).isoformat(),
                errors=["Post-processing timed out"],
            )

        duration = time.monotonic() - start
        return RunResult(
            exit_code=proc.returncode,
            stdout=proc.stdout.strip() if proc.stdout else "",
            stderr=proc.stderr.strip() if proc.stderr else "",
            duration_s=round(duration, 3),
            script=str(session_file),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def extract_ccl(self, def_file: Path, output_ccl: Path) -> bool:
        """Extract CCL from a .def file via ``cfx5cmds -read``."""
        installs = self.detect_installed()
        if not installs:
            return False

        bin_dir = Path(installs[0].path)
        cfx5cmds = bin_dir / "cfx5cmds.exe"
        if not cfx5cmds.is_file():
            cfx5cmds = bin_dir / "cfx5cmds"

        try:
            proc = subprocess.run(
                [str(cfx5cmds), "-read", "-def", str(def_file), "-text", str(output_ccl)],
                capture_output=True, text=True, timeout=60,
            )
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def export_monitor_data(self, res_file: Path, output_csv: Path) -> bool:
        """Export convergence monitor data via ``cfx5mondata``."""
        installs = self.detect_installed()
        if not installs:
            return False

        bin_dir = Path(installs[0].path)
        cfx5mondata = bin_dir / "cfx5mondata.exe"
        if not cfx5mondata.is_file():
            cfx5mondata = bin_dir / "cfx5mondata"

        try:
            proc = subprocess.run(
                [str(cfx5mondata), "-res", str(res_file), "-out", str(output_csv)],
                capture_output=True, text=True, timeout=120,
            )
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False
