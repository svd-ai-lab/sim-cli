"""Shared test configuration for sim tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Root fixtures directory — all tests reference this
FIXTURES = Path(__file__).parent / "fixtures"
EXECUTION = Path(__file__).parent / "execution"


# ── Synthetic driver injected for registry-dependent CLI tests ─────────────
#
# Pure-plugin architecture (Phase 3b): ``_BUILTIN_REGISTRY`` is empty —
# every driver, including the historical canaries openfoam and coolprop,
# now ships as an out-of-tree ``sim-plugin-<name>`` package. Several CLI
# tests need a *registered* driver that can run an arbitrary ``.py`` script
# as a subprocess (mock_solver.py); that contract used to be served by the
# in-tree pybamm/coolprop drivers. The fixture below injects a synthetic
# ``coolprop`` driver into both the registry and instance cache — keeping
# test command lines unchanged (``--solver=coolprop``) without needing
# any real plugin installed in the CI env.
#
# Active only for tests under ``tests/base/``; driver-specific suites (e.g.
# ``tests/drivers/<name>/``) opt out so their real driver code is exercised.


class _SyntheticPyDriver:
    """Lightweight driver that pretends ``.py`` scripts are runnable.

    Replaces the runtime contract of pybamm/coolprop so CLI smoke tests can
    invoke ``sim run --solver=coolprop mock_solver.py`` without an SDK gate.
    """
    @property
    def name(self) -> str:
        return "coolprop"

    @property
    def supports_session(self) -> bool:
        return False

    def detect(self, script: Path) -> bool:
        # Always False so the lint flow's iter_drivers+detect loop doesn't
        # claim arbitrary .py scripts. Tests use this driver via explicit
        # ``--solver=coolprop`` (which routes through get_driver, not detect).
        return False

    def lint(self, script: Path):
        from sim.driver import LintResult
        return LintResult(ok=True, diagnostics=[])

    def connect(self):
        from sim.driver import ConnectionInfo
        return ConnectionInfo(
            solver="coolprop", version="test", status="ok",
            message="synthetic driver (test fixture)",
        )

    def detect_installed(self):
        return []

    def parse_output(self, stdout: str) -> dict:
        import json
        for line in reversed(stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {}

    def run_file(self, script: Path):
        from sim.runner import run_subprocess
        return run_subprocess(
            [sys.executable, str(script)], script=script, solver=self.name,
        )

    def launch(self, **kwargs) -> dict:
        raise NotImplementedError("synthetic driver does not support sessions")

    def run(self, code: str, label: str = "") -> dict:
        raise NotImplementedError("synthetic driver does not support sessions")

    def disconnect(self) -> dict:
        return {"ok": True, "disconnected": True}


@pytest.fixture(autouse=True)
def _inject_synthetic_coolprop(request):
    """Inject a synthetic ``coolprop`` driver into the registry for base CLI tests.

    Active only under ``tests/base/``; driver-specific suites still exercise
    the real classes. Post-Phase-3b ``_BUILTIN_REGISTRY`` is empty, so the
    fixture patches BOTH the registry entries (so ``iter_drivers`` /
    ``sim solvers list`` / ``sim check`` see the synthetic) AND
    ``_INSTANCE_CACHE`` (so ``get_driver("coolprop")`` skips re-import).
    """
    if "tests/base/" not in str(request.fspath).replace("\\", "/"):
        yield
        return

    from sim import drivers as _drivers_pkg

    instance = _SyntheticPyDriver()
    fake_spec = ("coolprop", "tests.conftest:_SyntheticPyDriver")

    orig_builtin = list(_drivers_pkg._BUILTIN_REGISTRY)
    orig_registry = list(_drivers_pkg._REGISTRY)
    orig_cache = _drivers_pkg._INSTANCE_CACHE.pop("coolprop", None)

    _drivers_pkg._BUILTIN_REGISTRY.append(fake_spec)
    _drivers_pkg._REGISTRY.append(fake_spec)
    _drivers_pkg._INSTANCE_CACHE["coolprop"] = instance
    try:
        yield
    finally:
        _drivers_pkg._BUILTIN_REGISTRY[:] = orig_builtin
        _drivers_pkg._REGISTRY[:] = orig_registry
        _drivers_pkg._INSTANCE_CACHE.pop("coolprop", None)
        if orig_cache is not None:
            _drivers_pkg._INSTANCE_CACHE["coolprop"] = orig_cache
