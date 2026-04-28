"""LTspice driver for sim — thin adapter over ``sim_ltspice``.

The heavy work (install discovery, subprocess invocation, `.log`
encoding sniffing, `.raw` header parsing, `.asc` flattening) lives in
the standalone ``sim-ltspice`` package on PyPI. This module only
bridges between that library and sim-cli's ``DriverProtocol``.

Accepts ``.net`` / ``.cir`` / ``.sp`` netlists and ``.asc``
schematics. Schematics are flattened to a sibling netlist via
``sim_ltspice.run_asc`` before the actual solve.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sim_ltspice import NETLIST_SUFFIXES, find_ltspice
from sim_ltspice import RunResult as LtRunResult
from sim_ltspice.install import Install
from sim_ltspice.netlist import FlattenError
from sim_ltspice.runner import (
    LtspiceNotInstalled,
    UnsupportedInput,
    run_asc,
    run_net,
)

from sim.driver import (
    ConnectionInfo,
    Diagnostic,
    LintResult,
    RunResult,
    SolverInstall,
)


_ASC_SUFFIX = ".asc"
_ACCEPTED_SUFFIXES = NETLIST_SUFFIXES + (_ASC_SUFFIX,)

_ANALYSIS_RE = re.compile(
    r"^\s*\.(tran|ac|dc|op|noise|tf|four|fft|meas)\b",
    re.MULTILINE | re.IGNORECASE,
)
# In .asc schematics, analysis directives live inside TEXT ... ! lines:
#   TEXT 0 200 Left 2 !.tran 0 5m 0 1u
_ASC_ANALYSIS_RE = re.compile(
    r"^\s*TEXT\b.*!\s*\.(tran|ac|dc|op|noise|tf|four|fft|meas)\b",
    re.MULTILINE | re.IGNORECASE,
)


def _install_to_solver(inst: Install) -> SolverInstall:
    """Map ``sim_ltspice.Install`` → sim-cli ``SolverInstall``."""
    return SolverInstall(
        name="ltspice",
        version=inst.version or "unknown",
        path=inst.path,
        source=inst.source,
        extra={"exe": str(inst.exe)},
    )


def _measures_to_dict(log) -> dict[str, dict]:
    """Flatten ``sim_ltspice.LogResult.measures`` into sim-cli's JSON shape."""
    out: dict[str, dict] = {}
    for name, m in log.measures.items():
        entry: dict = {"expr": m.expr, "value": m.value}
        if m.window_from is not None:
            entry["from"] = m.window_from
        if m.window_to is not None:
            entry["to"] = m.window_to
        out[name] = entry
    return out


class LTspiceDriver:
    """Sim driver for LTspice — one-shot batch execution.

    Sessions are not supported: LTspice exposes no Python API or stdin
    protocol. Every invocation is a subprocess batch run routed through
    ``sim_ltspice.run_net``.
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
            return script.suffix.lower() in _ACCEPTED_SUFFIXES and script.is_file()
        except OSError:
            return False

    def lint(self, script: Path) -> LintResult:
        suffix = script.suffix.lower()
        if suffix not in _ACCEPTED_SUFFIXES:
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(
                    level="error",
                    message=(
                        f"Unsupported file type: {suffix} "
                        f"(expected one of {', '.join(_ACCEPTED_SUFFIXES)})"
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

        if suffix == _ASC_SUFFIX:
            return self._lint_asc(text)
        return self._lint_netlist(text)

    def _lint_netlist(self, text: str) -> LintResult:
        diagnostics: list[Diagnostic] = []
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

    def _lint_asc(self, text: str) -> LintResult:
        diagnostics: list[Diagnostic] = []
        if not text.strip():
            return LintResult(
                ok=False,
                diagnostics=[Diagnostic(level="error", message="Schematic is empty")],
            )
        if not text.lstrip().startswith("Version "):
            diagnostics.append(Diagnostic(
                level="error",
                message="Missing 'Version ' header — file is not an LTspice schematic",
            ))
        if not _ASC_ANALYSIS_RE.search(text):
            diagnostics.append(Diagnostic(
                level="error",
                message=(
                    "No SPICE analysis directive found in TEXT lines "
                    "(.tran / .ac / .dc / .op / .noise / .tf / .four)"
                ),
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
        return [_install_to_solver(i) for i in find_ltspice()]

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
        suffix = script.suffix.lower()
        if suffix not in _ACCEPTED_SUFFIXES:
            raise RuntimeError(
                f"ltspice driver only accepts {_ACCEPTED_SUFFIXES} "
                f"(got {script.suffix})"
            )
        # Mirror the driver-protocol contract: raise RuntimeError if
        # nothing is installed, preserving the sim-cli error surface even
        # though sim_ltspice raises its own LtspiceNotInstalled.
        if not self.detect_installed():
            raise RuntimeError(
                "LTspice is not installed; set SIM_LTSPICE_EXE or install it."
            )

        try:
            if suffix == _ASC_SUFFIX:
                lt: LtRunResult = run_asc(script)
            else:
                lt = run_net(script)
        except LtspiceNotInstalled as exc:
            raise RuntimeError(str(exc)) from exc
        except UnsupportedInput as exc:
            raise RuntimeError(str(exc)) from exc
        except FlattenError as exc:
            raise RuntimeError(f"Cannot flatten schematic: {exc}") from exc

        # Fold sim_ltspice's structured log + trace list into the JSON
        # summary so parse_output() can pick it up from stdout.
        parsed = {
            "measures": _measures_to_dict(lt.log),
            "errors": list(lt.log.errors),
            "warnings": list(lt.log.warnings),
            "elapsed_s": lt.log.elapsed_s,
            "traces": list(lt.raw_traces),
            "log": str(lt.log_path) if lt.log_path else None,
            "raw": str(lt.raw_path) if lt.raw_path else None,
        }

        errors: list[str] = [f"[log] {e}" for e in lt.log.errors]
        exit_code = lt.exit_code
        if exit_code == 0 and errors:
            exit_code = 1

        summary_json = json.dumps(parsed, separators=(",", ":"))
        stdout = (lt.stdout + "\n" + summary_json).strip() if lt.stdout else summary_json

        return RunResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=lt.stderr,
            duration_s=lt.duration_s,
            script=str(Path(script).resolve()),
            solver=self.name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            errors=errors,
        )

    # Session lifecycle stubs — one-shot driver, but DriverProtocol is
    # runtime_checkable so every method must exist. See `sim.driver`.
    def launch(self, **kwargs) -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError(f"{self.name} driver does not support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}
