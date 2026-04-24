"""Driver probe-wiring tests — verifies driver.run() attaches diagnostics.

Each of these drivers was refactored in the probe-extension pass:
  - existing logic moved to ``_dispatch(code, label)``
  - new ``run(code, label)`` wraps ``_dispatch`` with an ``InspectCtx`` and
    runs ``self.probes`` against it, attaching ``diagnostics`` + ``artifacts``
    to the result.

This test mocks ``_dispatch`` (so no real solver is needed) and verifies
that the wrapping ``run()`` actually populates ``diagnostics`` with the
expected probe codes.

Drivers only emit fact-type probes (process exit, stdout JSON tail, python
traceback, workdir diff). They do NOT emit solver-specific "this regex =
this error" diagnostics — that semantic interpretation is the agent's
job, not the driver's.

If you add a new driver, add a row here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# Each entry: (driver_module_path, class_name)
_DRIVERS = [
    ("sim.drivers.workbench.driver", "WorkbenchDriver"),
    ("sim.drivers.mechanical.driver", "MechanicalDriver"),
    ("sim.drivers.mapdl.driver", "MapdlDriver"),
    ("sim.drivers.lsdyna.driver", "LsDynaDriver"),
    ("sim.drivers.ansa.driver", "AnsaDriver"),
    ("sim.drivers.matlab.driver", "MatlabDriver"),
    ("sim.drivers.cfx.driver", "CfxDriver"),
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


@pytest.mark.parametrize("module_path,class_name", _DRIVERS)
def test_run_attaches_diagnostics(monkeypatch, tmp_path, module_path,
                                  class_name):
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


@pytest.mark.parametrize("module_path,class_name", _DRIVERS)
def test_process_meta_probe_fires(monkeypatch, tmp_path, module_path,
                                  class_name):
    """ProcessMetaProbe should always emit exit_zero on success."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout="ok", ok=True))

    out = drv.run("ignored")
    codes = [d["code"] for d in out["diagnostics"]]
    assert "sim.process.exit_zero" in codes, codes


@pytest.mark.parametrize("module_path,class_name", _DRIVERS)
def test_process_meta_probe_failure(monkeypatch, tmp_path, module_path,
                                    class_name):
    """On dispatch failure, exit_nonzero should fire."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout="", ok=False, error="oops"))

    out = drv.run("ignored")
    codes = [d["code"] for d in out["diagnostics"]]
    assert "sim.process.exit_nonzero" in codes, codes


@pytest.mark.parametrize("module_path,class_name", _DRIVERS)
def test_stdout_json_tail_probe_fires(monkeypatch, tmp_path, module_path,
                                      class_name):
    """When dispatch's stdout ends with JSON, StdoutJsonTailProbe fires."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    payload = json.dumps({"voltage": 3.72})
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout=f"line1\n{payload}", ok=True))

    out = drv.run("ignored")
    codes = [d["code"] for d in out["diagnostics"]]
    assert "sim.stdout.json_tail" in codes, codes


@pytest.mark.parametrize("module_path,class_name", _DRIVERS)
def test_no_driver_level_rule_codes(monkeypatch, tmp_path, module_path,
                                    class_name):
    """Drivers must not emit solver-specific error/warning codes themselves.

    Regex-based "this string = this error" judgements belong to the agent
    or sim-skills layer, not the driver. Only fact-type probe codes
    (sim.process.*, sim.stdout.*, sim.runtime.*, sim.workdir.*, traceback.*,
    sdk:attr.*, gui.*) are allowed from driver-default probes.
    """
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    # Feed the kind of text that the OLD rules would have matched for each
    # driver — none of it should produce solver-specific diagnostic codes.
    hostile = (
        "ScriptingException: foo\n"
        "Error: license checkout failed\n"
        "*** Error: bad\n"
        "ANSA error: bad mesh\n"
        "??? Undefined function 'foo'\n"
        "-- ERROR -- boundary missing\n"
        "[ERROR] JVM failure\n"
    )
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout=hostile, stderr=hostile, ok=False))

    out = drv.run("ignored")
    bad_prefixes = (
        "wb.", "mech.", "lsdyna.", "ansa.", "matlab.", "cfx.",
        "comsol.java.", "comsol.jvm.", "comsol.solve.", "comsol.sdk.method",
        "fluent.tui.", "fluent.scheme.", "fluent.solve.", "fluent.sdk.",
        "fluent.rpc.", "generic.exception",
    )
    for d in out["diagnostics"]:
        code = d.get("code", "")
        for pref in bad_prefixes:
            assert not code.startswith(pref), (
                f"{class_name} emitted solver-specific rule code {code!r} — "
                f"driver should not make semantic judgements. Full diag: {d}"
            )


@pytest.mark.parametrize("module_path,class_name", _DRIVERS)
def test_diagnostics_serializable(monkeypatch, tmp_path, module_path,
                                  class_name):
    """Diagnostics must round-trip through json so /exec can return them."""
    cls = _import_driver(module_path, class_name)
    drv = _make_driver(cls, tmp_path)
    monkeypatch.setattr(cls, "_dispatch",
                        _make_dispatch(stdout='{"x": 1}', ok=True))

    out = drv.run("ignored")
    json.dumps(out["diagnostics"])  # raises if not serializable
    json.dumps(out["artifacts"])
