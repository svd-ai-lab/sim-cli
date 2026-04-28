"""Tests for the conformance harness sim ships to plugin authors.

We exercise it against a hand-rolled fake driver (good and bad variants)
and against one real built-in driver to confirm round-trip works.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.driver import (
    ConnectionInfo,
    LintResult,
    RunResult,
    SolverInstall,
)
from sim.testing import (
    ConformanceFailure,
    assert_protocol_conformance,
    check_driver,
)


# ── Reference good driver ───────────────────────────────────────────────────


class _GoodDriver:
    name = "fakegood"
    supports_session = False

    def detect(self, script: Path) -> bool:
        return False

    def lint(self, script: Path) -> LintResult:
        return LintResult(ok=True, diagnostics=[])

    def connect(self) -> ConnectionInfo:
        return ConnectionInfo(solver=self.name, version="0", status="ok")

    def parse_output(self, stdout: str) -> dict:
        return {"metrics": {}, "warnings": [], "diagnostics": []}

    def run_file(self, script: Path) -> RunResult:
        return RunResult(
            exit_code=0, stdout="", stderr="",
            duration_s=0.0, script=str(script), solver=self.name, timestamp="t",
        )

    def detect_installed(self) -> list[SolverInstall]:
        return []

    # Protocol requires these as attributes; non-session drivers raise.
    def launch(self, **kwargs) -> dict:
        raise NotImplementedError("this driver doesn't support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError("this driver doesn't support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}


class _GoodSessionDriver(_GoodDriver):
    supports_session = True

    def launch(self, **kwargs) -> dict:
        return {"ok": True, "session_id": "test"}

    def run(self, code: str, label: str = "") -> dict:
        return {"ok": True}

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}


# ── Bad-driver variants for negative tests ──────────────────────────────────


class _MissingMethodDriver:
    name = "bad1"
    supports_session = False

    # No detect, no lint, etc.
    def detect_installed(self) -> list:
        return []


class _WrongReturnTypeDriver(_GoodDriver):
    name = "bad2"

    def parse_output(self, stdout: str):
        return "not a dict"


class _SessionAdvertisedButMissingDriver(_GoodDriver):
    name = "bad3"
    supports_session = True
    # Override the inherited stubs back to "missing" so the conformance check
    # for "advertised supports_session, but methods missing" fires.
    launch = None  # type: ignore[assignment]
    run = None    # type: ignore[assignment]
    disconnect = None  # type: ignore[assignment]


class _ConstructorRequiresArgs:
    name = "bad4"

    def __init__(self, required_arg):
        self.required_arg = required_arg


class _DetectInstalledRaises(_GoodDriver):
    def detect_installed(self):
        raise RuntimeError("forgot to make this safe")


# ── Tests ───────────────────────────────────────────────────────────────────


def test_good_driver_passes():
    failures = check_driver(_GoodDriver)
    assert failures == [], failures


def test_good_session_driver_passes():
    failures = check_driver(_GoodSessionDriver)
    assert failures == [], failures


def test_assert_passes_for_good_driver():
    # Smoke: doesn't raise.
    assert_protocol_conformance(_GoodDriver)


def test_missing_methods_flagged():
    failures = check_driver(_MissingMethodDriver)
    labels = {f.label for f in failures}
    # At minimum, the protocol-final check must complain.
    assert any(label.startswith("method:") for label in labels)


def test_wrong_return_type_flagged():
    failures = check_driver(_WrongReturnTypeDriver)
    assert any(f.label == "parse_output" for f in failures)


def test_advertised_session_methods_must_exist():
    failures = check_driver(_SessionAdvertisedButMissingDriver)
    labels = {f.label for f in failures}
    assert "session:launch" in labels
    assert "session:run" in labels
    assert "session:disconnect" in labels


def test_constructor_requiring_args_caught():
    with pytest.raises(ConformanceFailure):
        assert_protocol_conformance(_ConstructorRequiresArgs)


def test_detect_installed_must_be_safe():
    failures = check_driver(_DetectInstalledRaises)
    assert any(f.label == "detect_installed" for f in failures)


def test_assert_message_lists_every_failure():
    with pytest.raises(ConformanceFailure) as exc:
        assert_protocol_conformance(_SessionAdvertisedButMissingDriver)
    msg = str(exc.value)
    assert "session:launch" in msg
    assert "session:run" in msg
    assert "session:disconnect" in msg


# ── Real built-in driver smoke ──────────────────────────────────────────────


def test_built_in_coolprop_driver_check_runs():
    """We don't assert ``failures == []`` for built-ins (they may legitimately
    be in flux), only that the harness runs against a real driver class
    without crashing. This is a smoke test for the harness itself.
    """
    from sim.drivers.coolprop.driver import CoolPropDriver
    failures = check_driver(CoolPropDriver)
    assert isinstance(failures, list)


def test_every_built_in_driver_matches_protocol():
    """Every driver in ``_BUILTIN_REGISTRY`` must satisfy
    ``isinstance(driver, DriverProtocol)``.

    Why this is a hard assertion (unlike the smoke test above): plugins
    extracted out of the registry are required to pass
    :func:`assert_protocol_conformance` to ship. If built-ins drift below
    that bar — by missing one of the runtime-checkable methods — every
    extraction has to relitigate the contract. Keep parity.
    """
    import importlib

    from sim.driver import DriverProtocol
    from sim.drivers import _BUILTIN_REGISTRY

    failures: list[tuple[str, str]] = []
    for name, spec in _BUILTIN_REGISTRY:
        mod_path, cls_name = spec.split(":", 1)
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            instance = cls()
        except Exception as e:  # noqa: BLE001 — surface as a single failure line
            failures.append((name, f"{type(e).__name__}: {e}"))
            continue
        if not isinstance(instance, DriverProtocol):
            missing = [
                m for m in ("launch", "run", "disconnect")
                if not callable(getattr(instance, m, None))
            ]
            failures.append((name, f"missing methods: {missing}"))

    assert not failures, "drivers failing DriverProtocol structural check:\n" + "\n".join(
        f"  - {n}: {msg}" for n, msg in failures
    )
