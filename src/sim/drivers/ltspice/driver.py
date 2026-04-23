"""LTspice driver for sim.

LTspice (Analog Devices) is a free SPICE3 circuit simulator. There is no
Python API; control is via batch CLI:

    macOS native   : LTspice -b <netlist>.net
    Windows / wine : LTspice -Run -b <netlist>.net

Produces (beside the netlist):

    <stem>.log     UTF-16 LE text — .MEAS results, warnings, errors
    <stem>.raw     UTF-16 LE header + binary waveform data
    <stem>.op.raw  operating-point snapshot (if .op present)

Scope v1 accepts ``.net``, ``.cir``, ``.sp`` netlists. ``.asc`` schematics
need ``-netlist`` conversion which native macOS LTspice does not support;
deferred until wine / Windows paths are wired up.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import json
from pathlib import Path

from sim.driver import (
    ConnectionInfo,
    Diagnostic,
    LintResult,
    RunResult,
    SolverInstall,
)
from sim.runner import run_subprocess


NETLIST_SUFFIXES = (".net", ".cir", ".sp")


_ANALYSIS_RE = re.compile(
    r"^\s*\.(tran|ac|dc|op|noise|tf|four|fft|meas)\b",
    re.MULTILINE | re.IGNORECASE,
)

# LTspice .log lines like:  "vout_pk: MAX(v(out))=0.999955 FROM 0 TO 0.005"
_MEAS_RE = re.compile(
    r"^(?P<name>[A-Za-z_][\w]*)\s*:\s*"
    r"(?P<expr>[^=]+?)=(?P<value>[-+0-9.eE]+(?:[a-zA-Z]*)?)"
    r"(?:\s+FROM\s+(?P<from>[-+0-9.eE]+))?"
    r"(?:\s+TO\s+(?P<to>[-+0-9.eE]+))?\s*$",
    re.MULTILINE,
)

_ERROR_RE = re.compile(
    r"^(?:Error[:\s]|Fatal[:\s]|Convergence failed|Singular matrix|"
    r"Cannot find|Unknown (?:parameter|device))",
    re.MULTILINE | re.IGNORECASE,
)

_WARN_RE = re.compile(r"^WARNING[:\s].*$", re.MULTILINE | re.IGNORECASE)

_ELAPSED_RE = re.compile(
    r"Total elapsed time:\s*([0-9.]+)\s*seconds",
    re.IGNORECASE,
)


def _read_log(path: Path) -> str:
    """Read an LTspice .log file.

    Encoding varies by version:
      - LTspice 17.x (macOS native): UTF-16 LE, no BOM
      - LTspice 26.x (Windows): UTF-8, no BOM

    Sniff BOM first, then detect UTF-16 LE by the "0x00 at every odd byte"
    pattern (ASCII text under UTF-16 LE), else fall back to UTF-8.
    A naive chain that tries utf-16-le first produces garbage on UTF-8 logs
    because UTF-16 LE decoding never raises on arbitrary bytes.
    """
    if not path.is_file():
        return ""
    data = path.read_bytes()
    if not data:
        return ""
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if len(data) >= 4 and data[1] == 0 and data[3] == 0:
        return data.decode("utf-16-le", errors="replace")
    return data.decode("utf-8", errors="replace")


def _parse_log(text: str) -> dict:
    """Extract structured fields from an LTspice .log body."""
    measures: dict[str, dict] = {}
    for m in _MEAS_RE.finditer(text):
        try:
            val = float(re.sub(r"[a-zA-Z]+$", "", m.group("value")))
        except ValueError:
            continue
        entry: dict = {"expr": m.group("expr").strip(), "value": val}
        if m.group("from"):
            try:
                entry["from"] = float(m.group("from"))
            except ValueError:
                pass
        if m.group("to"):
            try:
                entry["to"] = float(m.group("to"))
            except ValueError:
                pass
        measures[m.group("name")] = entry

    errors = [m.group(0).strip() for m in _ERROR_RE.finditer(text)]
    warnings = [m.group(0).strip() for m in _WARN_RE.finditer(text)]
    elapsed: float | None = None
    em = _ELAPSED_RE.search(text)
    if em:
        try:
            elapsed = float(em.group(1))
        except ValueError:
            elapsed = None

    return {
        "measures": measures,
        "errors": errors,
        "warnings": warnings,
        "elapsed_s": elapsed,
    }


def _raw_trace_names(raw_path: Path) -> list[str]:
    """Return trace names from an LTspice .raw file, best-effort.

    Uses spicelib if installed; otherwise parses the UTF-16 LE header,
    which contains ``Variables:`` / ``Binary:`` sections.
    """
    if not raw_path.is_file():
        return []
    try:
        from spicelib import RawRead  # type: ignore
        return list(RawRead(str(raw_path)).get_trace_names())
    except Exception:
        pass
    # Fallback: read first 64KB, decode UTF-16 LE, split on 'Variables:'
    head = raw_path.read_bytes()[:65536]
    try:
        text = head.decode("utf-16-le", errors="replace")
    except Exception:
        return []
    # Header ends at 'Binary:' or 'Values:'
    for sentinel in ("Binary:", "Values:"):
        if sentinel in text:
            text = text.split(sentinel, 1)[0]
            break
    if "Variables:" not in text:
        return []
    body = text.split("Variables:", 1)[1]
    names: list[str] = []
    for line in body.splitlines():
        parts = line.strip().split()
        # lines look like: "<idx>\t<name>\t<type>"
        if len(parts) >= 2 and parts[0].isdigit():
            names.append(parts[1])
    return names


# ---------------------------------------------------------------------------
# Install discovery
# ---------------------------------------------------------------------------

def _macos_native_version(app_dir: Path) -> str | None:
    """Read CFBundleShortVersionString from LTspice.app/Contents/Info.plist."""
    info = app_dir / "Contents" / "Info.plist"
    if not info.is_file():
        return None
    try:
        # plutil is always present on macOS and handles both binary+xml plists.
        proc = subprocess.run(
            ["plutil", "-extract", "CFBundleShortVersionString",
             "raw", "-o", "-", str(info)],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    v = (proc.stdout or "").strip()
    return v or None


def _make_install(exe: Path, source: str) -> SolverInstall | None:
    if not exe.is_file():
        return None
    version: str | None = None
    app_dir: Path | None = None
    if sys.platform == "darwin":
        # exe sits at <...>.app/Contents/MacOS/LTspice
        parent = exe.parent.parent.parent
        if parent.suffix == ".app":
            app_dir = parent
            version = _macos_native_version(parent)
    # Windows: try FileDescription via `wmic` is slow; skip — version stays None.
    return SolverInstall(
        name="ltspice",
        version=version or "unknown",
        path=str(app_dir) if app_dir else str(exe.parent),
        source=source,
        extra={"exe": str(exe)},
    )


def _candidates_macos() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for base in (
        Path("/Applications/LTspice.app/Contents/MacOS/LTspice"),
        Path.home() / "Applications/LTspice.app/Contents/MacOS/LTspice",
    ):
        if base.is_file():
            out.append((base, "default-path:/Applications"))
    return out


def _candidates_windows() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    user = os.environ.get("USERPROFILE", "")
    win_candidates = [
        (Path(r"C:\Program Files\ADI\LTspice\LTspice.exe"), "default-path:Program Files"),
        (Path(r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe"), "default-path:LTspiceXVII"),
        (Path(r"C:\Program Files (x86)\LTC\LTspiceXVII\XVIIx64.exe"), "default-path:LTspiceXVII-x86"),
        (Path(r"C:\Program Files (x86)\LTC\LTspiceIV\scad3.exe"), "default-path:LTspiceIV"),
    ]
    if user:
        win_candidates.insert(
            0,
            (Path(user) / r"AppData\Local\Programs\ADI\LTspice\LTspice.exe",
             "default-path:LocalAppData"),
        )
    for p, src in win_candidates:
        if p.is_file():
            out.append((p, src))
    return out


def _candidates_env() -> list[tuple[Path, str]]:
    """$SIM_LTSPICE_EXE overrides everything else."""
    override = os.environ.get("SIM_LTSPICE_EXE")
    if not override:
        return []
    p = Path(override).expanduser()
    if p.is_file():
        return [(p, "env:SIM_LTSPICE_EXE")]
    return []


def _scan_installs() -> list[SolverInstall]:
    finders = [_candidates_env]
    if sys.platform == "darwin":
        finders.append(_candidates_macos)
    elif sys.platform == "win32":
        finders.append(_candidates_windows)
    # else: linux via wine is not auto-detected in v1; users can set SIM_LTSPICE_EXE.

    found: dict[str, SolverInstall] = {}
    for finder in finders:
        try:
            cands = finder()
        except Exception:
            continue
        for path, source in cands:
            inst = _make_install(path, source=source)
            if inst is None:
                continue
            key = str(Path(inst.extra["exe"]).resolve())
            found.setdefault(key, inst)
    # Stable order: env override first, then platform default.
    return list(found.values())


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class LTspiceDriver:
    """Sim driver for LTspice — one-shot batch execution.

    Sessions are not supported: LTspice exposes no Python API or stdin
    protocol. Every invocation is a subprocess batch run.
    """

    @property
    def name(self) -> str:
        return "ltspice"

    @property
    def supports_session(self) -> bool:
        return False

    # -- DriverProtocol ------------------------------------------------------

    def detect(self, script: Path) -> bool:
        try:
            return script.suffix.lower() in NETLIST_SUFFIXES and script.is_file()
        except OSError:
            return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        suffix = script.suffix.lower()
        if suffix not in NETLIST_SUFFIXES:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=(
                        f"Unsupported file type: {suffix} "
                        f"(expected one of {', '.join(NETLIST_SUFFIXES)})"
                    ),
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {exc}")],
            )

        if not text.strip():
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="Netlist is empty")],
            )

        if not _ANALYSIS_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message=(
                    "No SPICE analysis directive found "
                    "(.tran / .ac / .dc / .op / .noise / .tf / .four)"
                ),
            ))

        # .asc is a schematic, not a netlist — caught above by suffix check,
        # but guard against files mis-named with a netlist suffix.
        if text.lstrip().startswith("Version "):
            diagnostics.append(Diagnostic(
                level="error",
                message="Looks like an LTspice .asc schematic, not a netlist",
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="ltspice",
                version=None,
                status="not_installed",
                message=(
                    "LTspice not found. Install it from analog.com, "
                    "or set SIM_LTSPICE_EXE to the binary path."
                ),
            )
        top = installs[0]
        return ConnectionInfo(
            solver="ltspice",
            version=top.version,
            status="ok",
            message=f"LTspice {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        return _scan_installs()

    def parse_output(self, stdout: str) -> dict:
        """Return the last JSON line written by run_file."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path) -> RunResult:
        if script.suffix.lower() not in NETLIST_SUFFIXES:
            raise RuntimeError(
                f"ltspice driver only accepts {NETLIST_SUFFIXES} "
                f"(got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError(
                "LTspice is not installed; set SIM_LTSPICE_EXE or install it."
            )
        exe = installs[0].extra["exe"]

        script = script.resolve()
        # Native macOS LTspice accepts only '-b <netlist>'. Windows/wine
        # additionally accept '-Run' (same effect as -b here).
        if sys.platform == "darwin":
            cmd = [exe, "-b", script.as_posix()]
        else:
            cmd = [exe, "-Run", "-b", script.as_posix()]

        result = run_subprocess(cmd, script=script, solver=self.name)

        # LTspice doesn't write to stdout on batch success; parse the sibling
        # .log file for measurements + errors + warnings, then append a JSON
        # summary so parse_output() can pick it up.
        log_path = script.with_suffix(".log")
        raw_path = script.with_suffix(".raw")
        log_text = _read_log(log_path)
        parsed = _parse_log(log_text) if log_text else {
            "measures": {}, "errors": [], "warnings": [], "elapsed_s": None,
        }
        parsed["traces"] = _raw_trace_names(raw_path)
        parsed["log"] = str(log_path) if log_path.is_file() else None
        parsed["raw"] = str(raw_path) if raw_path.is_file() else None

        # If log reports errors, promote them into RunResult.errors and mark
        # the run as failed even if LTspice's own exit code was 0.
        log_errors = parsed["errors"]
        if log_errors:
            result.errors = list(result.errors) + [f"[log] {e}" for e in log_errors]
            if result.exit_code == 0:
                result.exit_code = 1

        summary_json = json.dumps(parsed, separators=(",", ":"))
        result.stdout = (result.stdout + "\n" + summary_json).strip()
        return result
