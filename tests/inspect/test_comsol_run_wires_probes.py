"""L2 test — ComsolDriver.run() returns diagnostics/artifacts.

Parallel to test_fluent_run_wires_probes. Uses a mock MPh-style Model
object so no real COMSOL is needed.
"""
from __future__ import annotations

import pytest


class _FakeJavaFeat:
    def __init__(self, kind):
        self._kind = kind

    def getString(self, key):
        return self._kind


class _FakeMphModelUtil:
    """Stub that ComsolDriver.disconnect() calls."""
    @staticmethod
    def disconnect():
        pass


class _FakeMphModel:
    """Mock of MPh's Model — just enough for default readers + `model` arg."""

    def __init__(self):
        self._feats = {"stat1": _FakeJavaFeat("stationary")}

    # MPh-style methods used by _default_comsol_readers
    def physics(self):
        return _FakeContainer(["phys1", "phys2"])

    def study(self):
        return _FakeContainer(["std1"])

    def material(self):
        return _FakeContainer(["mat1", "mat2"])

    def hist(self):
        return "<history stub>"


class _FakeContainer:
    """Stand-in for MPh's physics()/study()/material() sub-collections."""
    def __init__(self, tags):
        self._tags = tags

    def tags(self):
        return list(self._tags)


@pytest.fixture
def comsol_driver_with_session(tmp_path, monkeypatch):
    """Produce a ComsolDriver with a fake Model mounted.

    Uses a per-test tmp sim_dir (via monkeypatching SIM_DIR env var) to
    keep workdir-diff + transcript probes from contaminating between tests.
    """
    from sim.drivers.comsol.driver import ComsolDriver

    monkeypatch.setenv("SIM_DIR", str(tmp_path))
    d = ComsolDriver()
    # Fake session state the driver expects after a real launch().
    d._model = _FakeMphModel()
    d._model_util = _FakeMphModelUtil
    d._session_id = "test-session-comsol"
    d._connected_at = 0.0
    d._run_count = 0
    d._last_run = None
    # Phase 2 will also set self.probes = _default_comsol_probes(...) during
    # launch; since we bypass launch, set probes explicitly for the test:
    from sim.drivers.comsol.driver import _default_comsol_probes
    d.probes = _default_comsol_probes(enable_gui=False)
    d._sim_dir = tmp_path
    return d


def test_comsol_run_returns_diagnostics_key(comsol_driver_with_session):
    """Contract: driver.run(...) returns a dict with diagnostics + artifacts."""
    d = comsol_driver_with_session
    out = d.run("_result = 42", label="trivial")

    assert isinstance(out, dict)
    assert "diagnostics" in out, f"missing 'diagnostics' in {out.keys()}"
    assert "artifacts" in out, f"missing 'artifacts' in {out.keys()}"
    assert isinstance(out["diagnostics"], list)
    assert isinstance(out["artifacts"], list)


def test_comsol_run_success_lights_channel_1_and_4(comsol_driver_with_session):
    """Clean run should produce:
      #1 ProcessMeta info (sim.process.exit_zero)
      #4 SdkAttribute info for each default reader on MPh Model
    """
    d = comsol_driver_with_session
    out = d.run("_result = 'ok'", label="clean")

    codes = [x["code"] for x in out["diagnostics"]]
    # #1
    assert "sim.process.exit_zero" in codes
    # #4 — one entry per default reader (4 readers currently)
    attr_codes = [c for c in codes if c.startswith("comsol.sdk.attr.")]
    assert len(attr_codes) >= 2, f"expected >=2 #4 sdk-attr hits, got: {codes}"


def test_comsol_run_python_error_surfaces_as_traceback(comsol_driver_with_session):
    """Python NameError in snippet → #3+ traceback diagnostic."""
    d = comsol_driver_with_session
    out = d.run("x = undefined_xyz", label="nameerr")

    assert out["ok"] is False
    codes = [x["code"] for x in out["diagnostics"]]
    assert "python.NameError" in codes, f"got {codes}"


def test_comsol_run_preserves_existing_keys(comsol_driver_with_session):
    """ComsolDriver.run pre-Phase 2 returned run_id/ok/label/stdout/stderr/
    error/result/elapsed_s. All must remain present."""
    d = comsol_driver_with_session
    out = d.run("_result = 'x'", label="keys")
    for k in ("run_id", "ok", "label", "stdout", "stderr",
              "error", "result", "elapsed_s"):
        assert k in out, f"lost existing key {k}"


def test_comsol_run_timeout_returns_structured_diagnostic(comsol_driver_with_session):
    """Phase 2 goal #2: hung COMSOL snippet must surface as
    sim.runtime.snippet_timeout, not block forever."""
    import time as _time

    d = comsol_driver_with_session
    t0 = _time.time()
    out = d.run("import time; time.sleep(3.0)",
                label="timeout_test", timeout_s=0.3)
    wall = _time.time() - t0

    assert wall < 2.5, f"timeout helper itself blocked for {wall:.1f}s"
    assert out["ok"] is False
    codes = [x["code"] for x in out["diagnostics"]]
    assert "sim.runtime.snippet_timeout" in codes, f"codes={codes}"
