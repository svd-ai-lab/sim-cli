"""Star-CCM+ driver for sim.

Simcenter STAR-CCM+ is a CFD/multiphysics solver from Siemens. It uses
Java macros (.java files extending StarMacro) as its scripting language.
There is no pip-installable Python SDK — automation is via the command
line: ``starccm+ -batch macro.java [-np N] [case.sim]``.

Architecture category: **Subprocess** (like PyBaMM/COMSOL).
Scripts are self-contained Java macros; sim never imports Star-CCM+ libs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from sim.driver import ConnectionInfo, Diagnostic, LintResult, SolverInstall
from sim.runner import run_subprocess

# Detection patterns for Java macros
_RE_STAR_MACRO = re.compile(r"\bextends\s+StarMacro\b")
_RE_STAR_IMPORT = re.compile(r"^\s*import\s+star\.", re.MULTILINE)
_RE_GET_SIM = re.compile(r"\bgetActiveSimulation\s*\(\s*\)")

# Known install directory patterns (Windows)
_DEFAULT_DIRS = [
    r"E:\Program Files (x86)\Siemens",
    r"C:\Program Files\Siemens",
    r"C:\Program Files (x86)\Siemens",
    r"C:\Program Files\CD-adapco",
]


def _find_starccm_bat(install_root: Path) -> Path | None:
    """Given a Siemens install root, glob for starccm+.bat."""
    for d in sorted(install_root.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        # Pattern: <version-dir>/STAR-CCM+<ver>/star/bin/starccm+.bat
        for star_dir in d.glob("STAR-CCM+*/star/bin/starccm+.bat"):
            return star_dir
        # Also check directly: <version-dir>/star/bin/starccm+.bat
        bat = d / "star" / "bin" / "starccm+.bat"
        if bat.is_file():
            return bat
    return None


def _extract_version_from_path(bat_path: Path) -> str | None:
    """Extract version from path like .../STAR-CCM+21.02.007-R8/star/bin/starccm+.bat"""
    for part in bat_path.parts:
        if part.startswith("STAR-CCM+"):
            ver_str = part[len("STAR-CCM+"):]
            # Extract major.minor (e.g. "21.02" from "21.02.007-R8")
            m = re.match(r"(\d+\.\d+)", ver_str)
            if m:
                return m.group(1)
    # Try version_info.properties
    props = bat_path.parent.parent.parent / "version_info.properties"
    if props.is_file():
        for line in props.read_text(errors="replace").splitlines():
            if line.startswith("base_version="):
                ver = line.split("=", 1)[1].strip()
                m = re.match(r"(\d+\.\d+)", ver)
                if m:
                    return m.group(1)
    return None


def _probe_version_subprocess(bat_path: Path) -> str | None:
    """Try to get version by running starccm+ -version (quick probe)."""
    try:
        result = subprocess.run(
            [str(bat_path), "-version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        for line in result.stdout.splitlines():
            m = re.search(r"(\d+\.\d+\.\d+)", line)
            if m:
                parts = m.group(1).split(".")
                return f"{parts[0]}.{parts[1]}"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


class StarccmDriver:
    @property
    def name(self) -> str:
        return "starccm"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        """Check if script is a Star-CCM+ Java macro.

        Matches files that: (1) have .java extension, and (2) contain
        'extends StarMacro' indicating a Star-CCM+ macro class.
        """
        if not script.is_file():
            return False
        if script.suffix.lower() != ".java":
            return False
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return bool(_RE_STAR_MACRO.search(text))

    def lint(self, script: Path) -> LintResult:
        """Validate a Star-CCM+ Java macro.

        Checks:
        - File exists and is readable
        - Contains 'extends StarMacro' (error if missing)
        - Contains 'import star.*' (error if missing)
        - Contains 'getActiveSimulation()' (warning if missing)
        """
        diagnostics: list[Diagnostic] = []

        if not script.is_file():
            diagnostics.append(
                Diagnostic(level="error", message=f"File not found: {script}")
            )
            return LintResult(ok=False, diagnostics=diagnostics)

        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            diagnostics.append(
                Diagnostic(level="error", message=f"Cannot read file: {e}")
            )
            return LintResult(ok=False, diagnostics=diagnostics)

        has_star_macro = bool(_RE_STAR_MACRO.search(text))
        has_star_import = bool(_RE_STAR_IMPORT.search(text))
        has_get_sim = bool(_RE_GET_SIM.search(text))

        if not has_star_macro:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    message="No 'extends StarMacro' found — not a Star-CCM+ macro",
                )
            )

        if not has_star_import:
            diagnostics.append(
                Diagnostic(
                    level="error",
                    message="No 'import star.*' found — missing Star-CCM+ API imports",
                )
            )

        if has_star_macro and not has_get_sim:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    message="No getActiveSimulation() call — macro may not access the simulation",
                )
            )

        ok = not any(d.level == "error" for d in diagnostics)
        return LintResult(ok=ok, diagnostics=diagnostics)

    def connect(self) -> ConnectionInfo:
        """Check Star-CCM+ availability via detect_installed."""
        installs = self.detect_installed()
        if not installs:
            return ConnectionInfo(
                solver="starccm",
                version=None,
                status="not_installed",
                message="Star-CCM+ not found on this host",
            )
        top = installs[0]
        return ConnectionInfo(
            solver="starccm",
            version=top.version,
            status="ok",
            message=f"Star-CCM+ {top.version} at {top.path}",
            solver_version=top.version,
        )

    def detect_installed(self) -> list[SolverInstall]:
        """Find Star-CCM+ installations on this host.

        Scan chain:
        1. STAR_INSTALL / STARCCM_HOME environment variables
        2. Windows registry (Siemens STAR-CCM+)
        3. Default install directories glob
        """
        found: dict[str, SolverInstall] = {}

        def _record(bat_path: Path, source: str) -> None:
            bat_path = bat_path.resolve()
            key = str(bat_path)
            if key in found:
                return
            version = _extract_version_from_path(bat_path)
            if version is None:
                return
            install_root = bat_path.parent.parent.parent  # star/bin/starccm+.bat -> STAR-CCM+xxx
            found[key] = SolverInstall(
                name="starccm",
                version=version,
                path=str(install_root),
                source=source,
                extra={"starccm_bat": str(bat_path)},
            )

        # 1. Environment variables (CDLMD_LICENSE_FILE is for licensing, not detection)
        for var in ("STAR_INSTALL", "STARCCM_HOME"):
            val = os.environ.get(var)
            if val:
                p = Path(val)
                bat = p / "star" / "bin" / "starccm+.bat"
                if bat.is_file():
                    _record(bat, source=f"env:{var}")
                else:
                    # Maybe it points to the Siemens root
                    result = _find_starccm_bat(p)
                    if result:
                        _record(result, source=f"env:{var}")

        # 2. Windows registry
        try:
            import winreg
            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        i += 1
                        with winreg.OpenKey(key, subkey_name) as subkey:
                            try:
                                display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                if "STAR-CCM+" not in display_name:
                                    continue
                                install_loc = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                                p = Path(install_loc)
                                result = _find_starccm_bat(p)
                                if result:
                                    _record(result, source="registry")
                            except (OSError, FileNotFoundError):
                                continue
                    except OSError:
                        break
        except (ImportError, OSError):
            pass

        # 3. Default directories
        for dir_path in _DEFAULT_DIRS:
            p = Path(dir_path)
            if not p.is_dir():
                continue
            result = _find_starccm_bat(p)
            if result:
                _record(result, source=f"default-path:{dir_path}")

        return sorted(found.values(), key=lambda i: i.version, reverse=True)

    def parse_output(self, stdout: str) -> dict:
        """Extract structured JSON from Star-CCM+ output.

        Convention: macro prints a JSON object on stdout (possibly among
        other output). We take the last line that parses as JSON.
        """
        if not stdout or not stdout.strip():
            return {}
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    @staticmethod
    def _find_license_file(install: SolverInstall) -> Path | None:
        """Auto-detect license.dat near the installation."""
        install_path = Path(install.path)
        # Check parent directories for license.dat
        for parent in [install_path, install_path.parent, install_path.parent.parent]:
            lic = parent / "license.dat"
            if lic.is_file():
                return lic
        # Check common Siemens license locations
        for p in _DEFAULT_DIRS:
            lic = Path(p) / "license.dat"
            if lic.is_file():
                return lic
        return None

    def run_file(self, script: Path):
        """Execute a Star-CCM+ Java macro in batch mode.

        Runs: starccm+ -batch <macro.java> [-np N]

        Uses bytes mode + utf-8 decode with replace to handle CJK locale
        issues on Chinese/Japanese/Korean Windows.
        """
        import time
        from datetime import datetime, timezone
        from sim.driver import RunResult

        installs = self.detect_installed()
        if not installs:
            return RunResult(
                exit_code=127,
                stdout="",
                stderr="Star-CCM+ not found. Run 'sim check starccm' for details.",
                duration_s=0.0,
                script=str(script),
                solver=self.name,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        starccm_bat = installs[0].extra.get("starccm_bat", "starccm+")
        cmd = [starccm_bat, "-batch", str(script)]

        # Build env with license file auto-detection if not set
        env = dict(os.environ)
        if "CDLMD_LICENSE_FILE" not in env:
            license_file = self._find_license_file(installs[0])
            if license_file:
                env["CDLMD_LICENSE_FILE"] = str(license_file)

        start = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, env=env)
        duration = time.monotonic() - start

        # Decode with utf-8 + replace to avoid CJK codec crashes
        stdout = proc.stdout.decode("utf-8", errors="replace").strip() if proc.stdout else ""
        stderr = proc.stderr.decode("utf-8", errors="replace").strip() if proc.stderr else ""

        # Analyze ALL output for errors
        from sim.runner import detect_output_errors
        errors = detect_output_errors(stdout, stderr)
        # Star-CCM+ specific: check for Java compilation errors and license failures
        for text in (stdout, stderr):
            if not text:
                continue
            if re.search(r"Licensing problem:", text):
                errors.append(f"[stdout] Licensing problem")
            if re.search(r"^error:", text, re.MULTILINE):
                m = re.search(r"^error:.*", text, re.MULTILINE)
                if m and not any("error:" in e for e in errors):
                    errors.append(f"[stdout] {m.group(0)[:200]}")

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
