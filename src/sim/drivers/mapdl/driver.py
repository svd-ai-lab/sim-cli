"""Ansys MAPDL driver for sim.

Architecture: **SDK Persistent (gRPC variant)** — same family as the
Mechanical driver. PyMAPDL starts ``ANSYS241.exe -grpc`` on port 50052
and the client talks to MAPDL over gRPC.

Unlike Mechanical, MAPDL does **not** require a visible GUI window:
- MAPDL's gRPC server runs headless by default.
- PyVista-backed plotting is already off-screen capable, so
  ``mapdl.post_processing.plot_nodal_displacement(..., savefig=...)``
  produces a PNG without any display server. This is why Step 8.5 of
  the driver-development guide ("headless first") is trivially
  satisfied for MAPDL.

Phase 1 (this file): one-shot ``sim run script.py`` via subprocess.
Each script launches its own MAPDL instance via
``from ansys.mapdl.core import launch_mapdl``. The sim core process
never imports pymapdl (would drag in pyvista + vtk + scipy ~250 MB).

Phase 2 (optional, see runtime.py): persistent session — sim holds a
``Mapdl`` gRPC client in-process across ``sim exec`` calls. Only
implemented after Phase 1 is green against vendor verification files.

Detection is via regex on ``ansys.mapdl.core`` import statements —
PyMAPDL scripts are always Python, never raw APDL ``.dat`` / ``.mac``
files (those go through ``mapdl.input("file.dat")`` inside a Python
script, not as top-level inputs).
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess


_MAPDL_IMPORT = re.compile(
    r"^\s*(import\s+ansys\.mapdl|from\s+ansys\.mapdl\b)",
    re.MULTILINE,
)

# APDL card markers — not used for detect() (we only dispatch .py), but
# surfaced in lint() as a hint that the user pasted raw APDL into a .py
# file by mistake.
_APDL_CARD_MARKERS = re.compile(
    r"^\s*(/PREP7|/SOLU|/POST1|/POST26|/AUX2|/AUX15|FINISH\s*$)",
    re.MULTILINE | re.IGNORECASE,
)

_AWP_ROOT_RE = re.compile(r"^AWP_ROOT(\d{3})$")


def _probe_python_for_pymapdl(python_exe: Path) -> tuple[str, str | None] | None:
    """Run ``<python> -c 'import ansys.mapdl.core; find_mapdl()'`` and
    return ``(pymapdl_version, mapdl_version_str)``, or ``None`` if
    pymapdl is not importable there.

    Pure subprocess — never imports pymapdl into the caller.
    """
    if not python_exe.is_file():
        return None
    probe = (
        "import json, sys\n"
        "try:\n"
        "    import ansys.mapdl.core as pm\n"
        "    ver = pm.__version__\n"
        "except Exception:\n"
        "    print(json.dumps({'ok': False})); sys.exit(0)\n"
        "try:\n"
        "    from ansys.tools.path import find_mapdl\n"
        "    exe, mver = find_mapdl()\n"
        "except Exception:\n"
        "    exe, mver = None, None\n"
        "print(json.dumps({'ok': True, 'pymapdl': ver, 'mapdl_exe': exe,"
        " 'mapdl_ver': mver}))\n"
    )
    try:
        result = subprocess.run(
            [str(python_exe), "-c", probe],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return None
    if not data.get("ok"):
        return None
    return data["pymapdl"], data.get("mapdl_ver")


def _scan_awp_roots() -> list[tuple[str, Path]]:
    """Scan env for ``AWP_ROOT<xxx>`` vars → list of ``(version, root)``."""
    out: list[tuple[str, Path]] = []
    for k, v in os.environ.items():
        m = _AWP_ROOT_RE.match(k)
        if not m:
            continue
        root = Path(v)
        if not root.is_dir():
            continue
        vnum = m.group(1)  # '241' → '24.1'
        ver = f"{vnum[:2]}.{vnum[2]}"
        out.append((ver, root))
    return sorted(out, key=lambda x: x[0], reverse=True)


def _find_mapdl_exe(root: Path) -> Path | None:
    """Return ``<root>/ansys/bin/winx64/ANSYS<nnn>.exe`` if present."""
    bin_dir = root / "ansys" / "bin" / ("winx64" if os.name == "nt" else "linx64")
    if not bin_dir.is_dir():
        return None
    for name in sorted(bin_dir.iterdir(), reverse=True):
        if name.name.lower().startswith("ansys") and name.suffix.lower() == ".exe":
            # e.g. ANSYS241.exe — prefer versioned variants
            if re.match(r"(?i)^ansys\d{3}\.exe$", name.name):
                return name
    return None


def _default_mapdl_probes() -> list:
    """MAPDL probe list — generic_probes() only.

    No driver-layer semantic assertions: "what counts as an error" is the
    agent's job, not the driver's. Probes here only extract facts.
    """
    from sim.inspect import generic_probes  # noqa: PLC0415
    return generic_probes()


class MapdlDriver:
    """MAPDL driver — Phase 1 (one-shot) + Phase 2 (session)."""

    def __init__(self) -> None:
        self._runtime = None
        self._sim_dir: Path = Path(os.environ.get("SIM_DIR") or (Path.cwd() / ".sim"))
        self.probes: list = _default_mapdl_probes()

    @property
    def name(self) -> str:
        return "mapdl"

    @property
    def supports_session(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # detect / lint
    # ------------------------------------------------------------------

    def detect(self, script: Path) -> bool:
        if not script.is_file():
            return False
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return bool(_MAPDL_IMPORT.search(text))

    def lint(self, script: Path) -> LintResult:
        if not script.is_file():
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"File not found: {script}")],
            )
        text = script.read_text(encoding="utf-8", errors="replace")
        diagnostics: list[Diagnostic] = []

        has_import = bool(_MAPDL_IMPORT.search(text))
        if not has_import:
            if _APDL_CARD_MARKERS.search(text):
                diagnostics.append(Diagnostic(
                    level="error",
                    message=(
                        "Script contains APDL cards (/PREP7 etc.) but is not a"
                        " PyMAPDL Python script. Wrap raw APDL through"
                        " mapdl.input(...) inside a .py file driving PyMAPDL."
                    ),
                ))
            else:
                diagnostics.append(Diagnostic(
                    level="error", message="No ansys.mapdl.core import found"
                ))

        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(Diagnostic(
                level="error", message=f"Syntax error: {e.msg}", line=e.lineno
            ))
            tree = None

        if has_import and tree is not None:
            # Look for a launch_mapdl(...) or Mapdl(...) call — without one
            # the script cannot reach a running MAPDL.
            has_launch = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = (
                        fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name)
                        else None
                    )
                    if name in ("launch_mapdl", "Mapdl"):
                        has_launch = True
                        break
            if not has_launch:
                diagnostics.append(Diagnostic(
                    level="warning",
                    message=(
                        "No launch_mapdl(...) or Mapdl(...) call found — script"
                        " may not connect to an MAPDL instance"
                    ),
                ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    # ------------------------------------------------------------------
    # connect / detect_installed
    # ------------------------------------------------------------------

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="mapdl",
                version=None,
                status="not_installed",
                message=(
                    "pymapdl (ansys-mapdl-core) not importable, or no ANSYS"
                    " MAPDL binary found. Set AWP_ROOT<ver> or install with"
                    " `uv pip install ansys-mapdl-core`."
                ),
            )
        top = installs[0]
        return ConnectionInfo(
            solver="mapdl",
            version=top.version,
            status="ok",
            message=(
                f"MAPDL {top.extra.get('mapdl_ver') or '?'}"
                f" via pymapdl {top.extra.get('pymapdl', '?')} at {top.path}"
            ),
            solver_version=top.extra.get("mapdl_ver"),
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Find MAPDL installs.

        Chain:
        1. Probe sim's current Python for pymapdl (if present, trust
           ``find_mapdl()`` to locate the MAPDL exe via env vars).
        2. Fall back to manual ``AWP_ROOT<ver>`` scan when pymapdl is
           unavailable — still valid for ``sim run`` since the user's
           script will need its own pymapdl anyway.
        """
        out: list[SolverInstall] = []

        # 1) pymapdl probe
        probe = _probe_python_for_pymapdl(Path(sys.executable))
        if probe is not None:
            pm_ver, mapdl_ver = probe
            # Ask pymapdl where the MAPDL exe is
            try:
                from ansys.tools.path import find_mapdl  # type: ignore
                exe, _ = find_mapdl()
            except Exception:
                exe = None
            if mapdl_ver:
                short = str(mapdl_ver)
                out.append(SolverInstall(
                    name="mapdl",
                    version=short,
                    path=str(Path(exe).parent) if exe else "",
                    source="pymapdl:find_mapdl",
                    extra={"pymapdl": pm_ver, "mapdl_ver": short,
                           "mapdl_exe": exe or ""},
                ))

        # 2) AWP_ROOT fallback
        if not out:
            for ver, root in _scan_awp_roots():
                exe = _find_mapdl_exe(root)
                if not exe:
                    continue
                out.append(SolverInstall(
                    name="mapdl",
                    version=ver,
                    path=str(exe.parent),
                    source="env:AWP_ROOT",
                    extra={"mapdl_ver": ver, "mapdl_exe": str(exe)},
                ))

        return out

    # ------------------------------------------------------------------
    # run / parse_output
    # ------------------------------------------------------------------

    def parse_output(self, stdout: str) -> dict:
        """Last JSON line convention (same as pybamm)."""
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        return run_subprocess(
            [sys.executable, str(script)],
            script=script,
            solver=self.name,
        )

    # ------------------------------------------------------------------
    # session lifecycle (Phase 2)
    # ------------------------------------------------------------------

    def _ensure_runtime(self):
        if self._runtime is None:
            from sim.drivers.mapdl.runtime import MapdlSessionRuntime
            self._runtime = MapdlSessionRuntime()
        return self._runtime

    def launch(self, **kwargs) -> dict:
        """Start a persistent PyMAPDL session.

        Accepts (protocol-compat kwargs tolerated):
          workdir     — solver working directory (default: temp dir)
          exec_file   — path to ANSYS<ver>.exe (default: auto-detect)
          nproc       — MPI ranks (default: MAPDL's default)
          processors  — alias for nproc (generic /connect name)
          mode, ui_mode — accepted & ignored
        """
        return self._ensure_runtime().launch(**kwargs)

    def _dispatch(self, code: str, label: str = "snippet") -> dict:
        """Exec a Python snippet in the session namespace (no probes)."""
        return self._ensure_runtime().exec_snippet(code, label)

    def run(self, code: str, label: str = "snippet") -> dict:
        """Exec a Python snippet and attach inspect diagnostics.

        Namespace has: ``mapdl``, ``np``, ``launch_mapdl``, ``workdir``,
        ``_result``. Assign ``_result = ...`` to return data.
        """
        from sim.inspect import InspectCtx, collect_diagnostics       # noqa: PLC0415

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
            stdout=result.get("stdout", ""),
            stderr=result.get("stderr", "") or result.get("error", "") or "",
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

    def query(self, name: str) -> dict:
        """Named queries (session.summary, mesh.summary, workdir.files,
        results.summary, last.result)."""
        return self._ensure_runtime().query(name)

    def disconnect(self, **_kwargs) -> dict:
        """Tear down the session. Idempotent."""
        if self._runtime is None:
            return {"ok": True, "disconnected": True, "note": "no active session"}
        return self._runtime.disconnect()
