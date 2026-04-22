"""L2 test — PyFluentDriver.run() returns diagnostics/artifacts.

No real Fluent needed. We mount a dummy session on PyFluentRuntime and
exec simple snippets to verify the probe pipeline (baseline 3 probes)
is wired through `driver.run()` and surfaces structured diagnostics.

This is the last safety net before the real mixing_elbow L3 tests.
"""
from __future__ import annotations

import pytest


class _DummySession:
    """Just enough surface for PyFluentRuntime to register it."""
    def exit(self):
        pass


@pytest.fixture
def fluent_driver_with_session(tmp_path):
    """Produce a PyFluentDriver with a fake session registered.

    Uses a per-test tmp sim_dir so leftover .trn/.cas.h5 from prior
    integration runs can't contaminate the Channel 7 transcript probe.
    """
    from sim.drivers.fluent.driver import PyFluentDriver

    d = PyFluentDriver(sim_dir=tmp_path)
    d._runtime.register_session(
        session_id="test-session",
        mode="solver",
        source="launch",
        session=_DummySession(),
    )
    return d


def test_run_returns_diagnostics_key(fluent_driver_with_session):
    """Contract: driver.run(...) always returns a dict containing a
    `diagnostics` list (may be empty) and an `artifacts` list."""
    d = fluent_driver_with_session
    out = d.run("_result = 42", label="trivial")

    assert isinstance(out, dict)
    assert "diagnostics" in out, f"missing 'diagnostics' in {out.keys()}"
    assert "artifacts" in out, f"missing 'artifacts' in {out.keys()}"
    assert isinstance(out["diagnostics"], list)
    assert isinstance(out["artifacts"], list)


def test_run_success_emits_only_info_severities(fluent_driver_with_session):
    """A clean snippet must NOT emit any severity=error diagnostic."""
    d = fluent_driver_with_session
    out = d.run("_result = 2 + 2", label="clean")

    errs = [x for x in out["diagnostics"] if x["severity"] == "error"]
    assert errs == [], f"unexpected error diagnostics on clean run: {errs}"
    # at least one info from ProcessMetaProbe
    infos = [x for x in out["diagnostics"] if x["severity"] == "info"]
    assert len(infos) >= 1


def test_run_name_error_surfaces_as_python_diagnostic(fluent_driver_with_session):
    """Python NameError inside a snippet must show up as a structured
    diagnostic with code=python.NameError."""
    d = fluent_driver_with_session
    out = d.run("x = undefined_thing", label="nameerr")

    assert out["ok"] is False
    codes = [x["code"] for x in out["diagnostics"]]
    assert "python.NameError" in codes, \
        f"expected python.NameError in diagnostics; got {codes}\nerror={out.get('error')}"
    # the matching diagnostic should name the undefined identifier
    nameerr = next(x for x in out["diagnostics"] if x["code"] == "python.NameError")
    assert "undefined_thing" in nameerr["message"]
    assert nameerr["source"] == "traceback"
    assert nameerr["severity"] == "error"


def test_run_failure_also_emits_process_nonzero(fluent_driver_with_session):
    """On any failure, ProcessMetaProbe emits exit_nonzero (we map ok=False → exit_code=1)."""
    d = fluent_driver_with_session
    out = d.run("raise ValueError('boom')", label="raise")

    codes = [x["code"] for x in out["diagnostics"]]
    assert "sim.process.exit_nonzero" in codes
    assert "python.ValueError" in codes


def test_run_dict_serializable(fluent_driver_with_session):
    """Output must be json.dumps-able — server.py needs this."""
    import json

    d = fluent_driver_with_session
    out = d.run("_result = {'k': 1}", label="ok")
    json.dumps(out, default=str)  # should not raise


def test_run_preserves_existing_top_level_keys(fluent_driver_with_session):
    """Adding diagnostics/artifacts must not displace existing contract keys."""
    d = fluent_driver_with_session
    out = d.run("_result = 99", label="keys")
    for k in ("run_id", "ok", "label", "stdout", "stderr", "error", "result"):
        assert k in out, f"lost existing key {k}"
    assert out["result"] == 99


def test_run_hung_snippet_returns_timeout_diagnostic(fluent_driver_with_session):
    """Phase 2 goal #2: if a snippet blocks past timeout_s, we must return
    ok=False + a sim.runtime.snippet_timeout diagnostic — NOT hang forever."""
    import time as _time

    d = fluent_driver_with_session
    t0 = _time.time()
    # Use a VERY short timeout and a snippet that sleeps past it. The real
    # Fluent-RPC-hang scenario (write_case("Z:/...")) is too slow to L1-test;
    # a time.sleep exercises the same code path.
    code = "import time; time.sleep(3.0)"
    # Pass timeout via driver.run kwarg (needs to be plumbed)
    out = d.run(code, label="timeout_test", timeout_s=0.3)
    wall = _time.time() - t0

    # 1. returned promptly, did not hang
    assert wall < 2.5, f"timeout helper itself blocked for {wall:.1f}s"
    # 2. marked as failure
    assert out["ok"] is False
    # 3. error string mentions timeout
    err = out.get("error") or ""
    assert "timeout" in err.lower() or "hung" in err.lower(), f"error={err!r}"
    # 4. probe layer emitted a structured timeout diagnostic
    codes = [d["code"] for d in out["diagnostics"]]
    assert "sim.runtime.snippet_timeout" in codes, f"codes={codes}"
