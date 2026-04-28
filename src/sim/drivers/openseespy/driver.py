"""OpenSeesPy driver for sim.

OpenSeesPy is the Python interpreter wrapper for OpenSees, an
earthquake-engineering structural FEM framework from PEER (UC Berkeley).
Distributed as pip wheel `openseespy` + platform-specific
`openseespylinux` / `openseespywin` / `openseespymac` companion
package that contains the compiled C++ core.

Agent scripts:
    import openseespy.opensees as ops
    ops.wipe(); ops.model('basic', '-ndm', 2, '-ndf', 3)
    ops.node(...); ops.element(...); ops.timeSeries/pattern/...
    ops.system('BandGeneral'); ops.analyze(N)

NOTE: the OpenSees C++ core prints `Process 0 Terminating` to stderr
on interpreter exit; this is benign and not a real error.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess


_IMPORT_RE = re.compile(
    r"^\s*(import\s+openseespy|from\s+openseespy\b)", re.MULTILINE,
)
_USAGE_RE = re.compile(
    r"\bops\.(model|node|element|fix|timeSeries|pattern|analyze|"
    r"system|integrator|algorithm|analysis|nodeDisp|nodeReaction|"
    r"eigen|recorder)\b",
)


def _probe_python_for_openseespy(python_exe: Path) -> str | None:
    if not python_exe.is_file():
        return None
    # importlib.metadata works on 3.8+; fallback to importlib_metadata or pkg_resources
    code = (
        "import sys\n"
        "v = None\n"
        "try:\n"
        "    if sys.version_info >= (3, 8):\n"
        "        import importlib.metadata as md\n"
        "    else:\n"
        "        import importlib_metadata as md\n"
        "    v = md.version('openseespy')\n"
        "except Exception:\n"
        "    try:\n"
        "        import pkg_resources\n"
        "        v = pkg_resources.get_distribution('openseespy').version\n"
        "    except Exception:\n"
        "        pass\n"
        "print(v or '')\n"
    )
    try:
        proc = subprocess.run(
            [str(python_exe), "-c", code],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    v = (proc.stdout or "").strip()
    if not v:
        return None
    # Verify the C extension actually loads
    try:
        p2 = subprocess.run(
            [str(python_exe), "-c", "import openseespy.opensees as _o"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if p2.returncode != 0:
        return None
    return v


class OpenSeesPyDriver:
    """Sim driver for OpenSeesPy (PEER's structural FEM via Python)."""

    @property
    def name(self) -> str:
        return "openseespy"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        try:
            if script.suffix.lower() != ".py":
                return False
            text = script.read_text(encoding="utf-8", errors="replace")
            return bool(_IMPORT_RE.search(text))
        except (OSError, UnicodeDecodeError):
            return False

    def lint(self, script: Path) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if script.suffix.lower() != ".py":
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=f"Unsupported file type: {script.suffix} (expected .py)",
                )],
            )
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message=f"Cannot read: {e}")],
            )

        if not _IMPORT_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message="No `import openseespy` / `from openseespy` found",
            ))

        try:
            ast.parse(text)
        except SyntaxError as e:
            diagnostics.append(Diagnostic(
                level="error", message=f"Syntax error: {e}", line=e.lineno,
            ))

        if _IMPORT_RE.search(text) and not _USAGE_RE.search(text):
            diagnostics.append(Diagnostic(
                level="warning",
                message=(
                    "No ops.model / ops.node / ops.element / ops.analyze call "
                    "— script may not do anything"
                ),
            ))

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="openseespy", version=None, status="not_installed",
                message="openseespy not importable from any known Python env",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="openseespy", version=top.version, status="ok",
            message=f"OpenSeesPy {top.version} in {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        found: dict[str, SolverInstall] = {}

        def _record(python: Path, source: str) -> None:
            ver = _probe_python_for_openseespy(python)
            if ver is None:
                return
            key = str(python.resolve())
            if key in found:
                return
            short = ".".join(ver.split(".")[:2])
            found[key] = SolverInstall(
                name="openseespy", version=short,
                path=str(python.parent), source=source,
                extra={"raw_version": ver, "python": str(python)},
            )

        _record(Path(sys.executable), "sys.executable")
        for name in ("python3", "python"):
            p = shutil.which(name)
            if p:
                _record(Path(p), f"which:{name}")
        return sorted(found.values(), key=lambda i: i.version, reverse=True)

    def parse_output(self, stdout: str) -> dict:
        # Skip OpenSees banner/exit chatter; look for last JSON line.
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        if script.suffix.lower() != ".py":
            raise RuntimeError(
                f"openseespy driver only accepts .py scripts (got {script.suffix})"
            )
        installs = self.detect_installed()
        if not installs:
            raise RuntimeError("OpenSeesPy is not installed in any known Python env")
        python_exe = installs[0].extra.get("python", sys.executable)
        return run_subprocess(
            [python_exe, str(script)], script=script, solver=self.name,
        )

    # Session lifecycle stubs — one-shot driver, but DriverProtocol is
    # runtime_checkable so every method must exist. See `sim.driver`.
    def launch(self, **kwargs) -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}
