"""Driver probe-wiring tests — verifies driver.run() attaches diagnostics.

Each of these drivers was refactored in the probe-extension pass:
  - existing logic moved to ``_dispatch(code, label)``
  - new ``run(code, label)`` wraps ``_dispatch`` with an ``InspectCtx`` and
    runs ``self.probes`` against it, attaching ``diagnostics`` + ``artifacts``
    to the result.

This test mocks ``_dispatch`` (so no real solver is needed) and verifies
that the wrapping ``run()`` actually populates ``diagnostics`` with the
expected probe codes.

If you add a new driver via the probe-extension skill, add a row here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# Each entry: (driver_module_path, class_name, marker_text_for_solver_specific_rule)
# The "marker" is text inserted into mocked stdout that the driver's
# TextStreamRulesProbe should match.
_DRIVERS = [
    ("sim.drivers.workbench.driver", "WorkbenchDriver",
     "ScriptingException: foo", "wb.scripting.exception"),
    ("sim.drivers.mechanical.driver", "MechanicalDriver",
     "Error: license checkout failed", "mech.scripting.error"),
    ("sim.drivers.mapdl.driver", "MapdlDriver",
     None, None),  # MAPDL has no driver-specific stream probe
    ("sim.drivers.lsdyna.driver", "LsDynaDriver",
     "*** Error: oops", "lsdyna.solver.error"),
    ("sim.drivers.ansa.driver", "AnsaDriver",
     "ANSA error: bad mesh", "ansa.scripting.error"),
    ("sim.drivers.matlab.driver", "MatlabDriver",
     "??? Undefined function 'foo'", "matlab.script.error"),
    ("sim.drivers.cfx.driver", "CfxDriver",
     "-- ERROR -- boundary missing", "cfx.post.error"),
]


def _make_dispatch(stdout="", stderr="", ok=True, error=None, result=None):
    """Build a fake _dispatch that returns the given result dict."""
    def _fake(self, code, label="snippet"):
        return {
            "ok": ok,
            "label": label,
            "stdout": stdout,
            "stderr": stderr,
            "error": error,
            "result": result,
            "elapsed_s": 0.05,
        }
    return _fake


def _make_driver(cls, tmp_path):
    """Construct a driver with probes stripped of GUI/Screenshot probes.

    Mechanical defaults to enable_gui=True, which would invoke pywinauto
    against the host desktop on every probe pass — slow and intrusive in
    unit tests.  Stripping those probes keeps the test focused on the
    wiring (does run() attach diagnostics?) without side effects.
    """
    from sim.inspect import GuiDialogProbe, ScreenshotProbe
    drv = cls()
    drv._sim_dir = tmp_path
    drv.probes = [
        p for p in drv.probes
        if not isinstance(p, (GuiDialogProbe, ScreenshotProbe))
    ]
    return drv


def _import_driver(module_path: str, class_name: str):
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def _drivers_with_marker():
    """Pytest parametrize feed for the solver-specific marker test."""
    return [
        (mp, cn, marker, code)
        for mp, cn, marker, code in _DRIVERS
        if marker is not None
    ]


@pytest.mark.parametrize("module_path,class_name,_marker,_code", _DRIVERS)
def test_run_attaches_diagnostics(monkeypatch, tmp_path, module_path,
                                  class_name, _marker, _code):
    """run() must always populate diagnostics + artifacts as lists of dicts."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout='{"k": 1}', ok=True))

    out = drv.run("ignored code")
    assert isinstance(out.get("diagnostics"), list), (
        f"{class_name}.run() did not attach diagnostics list")
    assert isinstance(out.get("artifacts"), list)
    assert out["diagnostics"], (
        f"{class_name}.run() returned empty diagnostics — probes did not fire")
    for d in out["diagnostics"]:
        assert isinstance(d, dict)
        assert "code" in d, f"diagnostic missing 'code' field: {d}"


@pytest.mark.parametrize("module_path,class_name,_marker,_code", _DRIVERS)
def test_process_meta_probe_fires(monkeypatch, tmp_path, module_path,
                                  class_name, _marker, _code):
    """ProcessMetaProbe should always emit exit_zero on success."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout="ok", ok=True))

    out = drv.run("ignored")
    codes = [d["code"] for d in out["diagnostics"]]
    assert "sim.process.exit_zero" in codes, codes


@pytest.mark.parametrize("module_path,class_name,_marker,_code", _DRIVERS)
def test_process_meta_probe_failure(monkeypatch, tmp_path, module_path,
                                    class_name, _marker, _code):
    """On dispatch failure, exit_nonzero should fire."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout="", ok=False, error="oops"))

    out = drv.run("ignored")
    codes = [d["code"] for d in out["diagnostics"]]
    assert "sim.process.exit_nonzero" in codes, codes


@pytest.mark.parametrize("module_path,class_name,_marker,_code", _DRIVERS)
def test_stdout_json_tail_probe_fires(monkeypatch, tmp_path, module_path,
                                      class_name, _marker, _code):
    """When dispatch's stdout ends with JSON, StdoutJsonTailProbe fires."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    payload = json.dumps({"voltage": 3.72})
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout=f"line1\n{payload}", ok=True))

    out = drv.run("ignored")
    codes = [d["code"] for d in out["diagnostics"]]
    assert "sim.stdout.json_tail" in codes, codes


@pytest.mark.parametrize("module_path,class_name,marker,code",
                         _drivers_with_marker())
def test_solver_specific_rule_fires(monkeypatch, tmp_path, module_path,
                                    class_name, marker, code):
    """Driver-specific TextStreamRulesProbe should match its known patterns."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    # Workbench scans stdout; Mechanical scans stdout; LS-DYNA scans stderr.
    if class_name == "LsDynaDriver":
        dispatch = _make_dispatch(stdout="", stderr=marker, ok=False)
    else:
        dispatch = _make_dispatch(stdout=marker, ok=False)
    monkeypatch.setattr(cls, "_dispatch", dispatch)

    out = drv.run("ignored")
    codes = [d["code"] for d in out["diagnostics"]]
    assert code in codes, f"expected {code} in {codes}"


@pytest.mark.parametrize("module_path,class_name,_marker,_code", _DRIVERS)
def test_diagnostics_serializable(monkeypatch, tmp_path, module_path,
                                  class_name, _marker, _code):
    """Diagnostics must round-trip through json so /exec can return them."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout='{"x": 1}', ok=True))

    out = drv.run("ignored")
    json.dumps(out["diagnostics"])  # raises if not serializable
    json.dumps(out["artifacts"])
