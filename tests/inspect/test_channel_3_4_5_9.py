"""L1 unit tests — Channels 3 / 4 / 5 / 9.

Channel 3: StdoutJsonTailProbe
Channel 4: SdkAttributeProbe
Channel 5: DomainExceptionMapProbe
Channel 9: WorkdirDiffProbe
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _ctx(**kw):
    from sim.inspect import InspectCtx

    defaults = dict(
        stdout="", stderr="", workdir="/tmp",
        wall_time_s=0.0, exit_code=0, driver_name="fluent", session_ns={},
    )
    defaults.update(kw)
    return InspectCtx(**defaults)


# ── Channel 3 StdoutJsonTailProbe ──────────────────────────────────────────────


def test_stdout_json_probe_finds_tail_json():
    from sim.inspect import StdoutJsonTailProbe

    stdout = (
        "iterating...\n"
        "step 1 done\n"
        "step 2 done\n"
        '{"outlet_temp_C": 301.2, "iters": 150}\n'
    )
    p = StdoutJsonTailProbe()
    r = p.probe(_ctx(stdout=stdout))
    assert len(r.diagnostics) == 1
    d = r.diagnostics[0]
    assert d.source == "stdout:json"
    assert d.code == "sim.stdout.json_tail"
    assert d.extra["source_kind"] == "stdout"
    assert d.extra["value"] == {"outlet_temp_C": 301.2, "iters": 150}


def test_stdout_json_probe_ignores_non_object_lines():
    from sim.inspect import StdoutJsonTailProbe

    # last non-JSON line, then a JSON one earlier
    stdout = '{"x": 1}\nnot a json line\n'
    r = StdoutJsonTailProbe().probe(_ctx(stdout=stdout))
    assert len(r.diagnostics) == 1
    assert r.diagnostics[0].extra["value"] == {"x": 1}


def test_stdout_json_probe_falls_back_to_session_result():
    from sim.inspect import StdoutJsonTailProbe

    r = StdoutJsonTailProbe().probe(
        _ctx(stdout="some text without json",
             session_ns={"_result": {"k": "v"}})
    )
    assert len(r.diagnostics) == 1
    d = r.diagnostics[0]
    assert d.extra["source_kind"] == "session_result"
    assert d.extra["value"] == {"k": "v"}


def test_stdout_json_probe_no_match_no_output():
    from sim.inspect import StdoutJsonTailProbe

    r = StdoutJsonTailProbe().probe(_ctx(stdout="nothing useful here"))
    assert r.diagnostics == []


def test_stdout_json_probe_applies_gated_on_signal():
    from sim.inspect import StdoutJsonTailProbe

    p = StdoutJsonTailProbe()
    assert p.applies(_ctx(stdout="has text")) is True
    assert p.applies(_ctx(session_ns={"_result": {"a": 1}})) is True
    assert p.applies(_ctx()) is False


# ── Channel 4 SdkAttributeProbe ────────────────────────────────────────────────


class _FakeViscous:
    def __init__(self, model_value="k-epsilon"):
        self._model = model_value

    def __call__(self, *a, **kw):
        return self._model


class _FakeSetup:
    def __init__(self):
        self.models = type("m", (), {})()
        self.models.viscous = type("v", (), {})()
        self.models.viscous.model = _FakeViscous("k-omega-sst")
        self.models.energy = type("e", (), {"enabled": False})()


class _FakeSolverSession:
    def __init__(self):
        self.setup = _FakeSetup()


def test_sdk_attribute_probe_reads_callable_attribute():
    from sim.inspect import SdkAttributeProbe

    session = _FakeSolverSession()
    p = SdkAttributeProbe(
        attr_paths=["setup.models.viscous.model"],
    )
    r = p.probe(_ctx(session_ns={"session": session}))
    diags_for_attr = [d for d in r.diagnostics
                      if d.code == "fluent.sdk.attr.setup.models.viscous.model"]
    assert len(diags_for_attr) == 1
    d = diags_for_attr[0]
    assert d.severity == "info"
    assert d.source == "sdk:attr:setup.models.viscous.model"
    assert "k-omega-sst" in d.message
    assert d.extra["value_repr"] == "'k-omega-sst'"


def test_sdk_attribute_probe_handles_plain_attribute():
    from sim.inspect import SdkAttributeProbe

    session = _FakeSolverSession()
    p = SdkAttributeProbe(
        attr_paths=["setup.models.energy.enabled"],
    )
    d = p.probe(_ctx(session_ns={"session": session})).diagnostics[0]
    assert d.code == "fluent.sdk.attr.setup.models.energy.enabled"
    assert "False" in d.message


def test_sdk_attribute_probe_graceful_on_missing_attribute():
    from sim.inspect import SdkAttributeProbe

    session = _FakeSolverSession()
    p = SdkAttributeProbe(
        attr_paths=["setup.models.nonexistent.foo"],
    )
    diags = p.probe(_ctx(session_ns={"session": session})).diagnostics
    # Must emit a warning, not crash
    warn = [d for d in diags if d.severity == "warning"]
    assert len(warn) == 1
    # Phase 2: read-failed code is driver-neutral (both fluent + comsol share it)
    assert warn[0].code == "sim.sdk.attr_read_failed"
    assert "nonexistent" in warn[0].message


def test_sdk_attribute_probe_applies_only_with_session():
    from sim.inspect import SdkAttributeProbe

    p = SdkAttributeProbe(attr_paths=["setup.x"])
    assert p.applies(_ctx(session_ns={})) is False
    assert p.applies(_ctx(session_ns={"session": object()})) is True


# ── Channel 4 — readers mode (COMSOL / Java-API style) ────────────────────────


class _FakeJavaFeature:
    """Mock of COMSOL-style `model.feature('stat1').getString('type')`."""

    def __init__(self, kind):
        self._kind = kind

    def getString(self, key):
        assert key == "type"
        return self._kind


class _FakeComsolModel:
    def __init__(self):
        self._feats = {"stat1": _FakeJavaFeature("stationary"),
                       "time1": _FakeJavaFeature("time-dependent")}

    def feature(self, tag=None):
        if tag is None:
            return self
        return self._feats[tag]

    def tags(self):
        return list(self._feats.keys())

    def physics_count(self):
        return 3


def test_sdk_attribute_probe_readers_mode_java_api_style():
    """COMSOL-style: reader is a plain callable over the session object,
    not a getattr-chain."""
    from sim.inspect import SdkAttributeProbe

    model = _FakeComsolModel()
    p = SdkAttributeProbe(
        readers=[
            ("model.feature.stat1.type",
             lambda s: s.feature("stat1").getString("type")),
            ("model.feature_count",
             lambda s: len(s.feature().tags())),
            ("model.physics_count",
             lambda s: s.physics_count()),
        ],
        source_prefix="sdk:attr",
        code_prefix="comsol.sdk.attr",
    )
    r = p.probe(_ctx(session_ns={"session": model}))

    stat_diag = next(d for d in r.diagnostics
                     if d.code == "comsol.sdk.attr.model.feature.stat1.type")
    assert stat_diag.severity == "info"
    assert "stationary" in stat_diag.message

    cnt_diag = next(d for d in r.diagnostics
                    if d.code == "comsol.sdk.attr.model.feature_count")
    assert "2" in cnt_diag.message

    phys_diag = next(d for d in r.diagnostics
                     if d.code == "comsol.sdk.attr.model.physics_count")
    assert "3" in phys_diag.message


def test_sdk_attribute_probe_readers_mode_reader_raises():
    """A reader raising must NOT crash the probe — emit a warning diag."""
    from sim.inspect import SdkAttributeProbe

    def _broken(session):
        raise RuntimeError("java.lang.NullPointerException")

    p = SdkAttributeProbe(
        readers=[("broken.path", _broken)],
        source_prefix="sdk:attr",
        code_prefix="comsol.sdk.attr",
    )
    diags = p.probe(_ctx(session_ns={"session": object()})).diagnostics
    warns = [d for d in diags if d.severity == "warning"]
    assert len(warns) == 1
    # Warning code should be probe-shared (not driver-specific "fluent.*")
    assert warns[0].code in ("sim.sdk.attr_read_failed", "fluent.sdk.attr_read_failed")
    assert "NullPointerException" in warns[0].message


def test_sdk_attribute_probe_rejects_both_readers_and_attr_paths():
    """Pass EITHER readers OR attr_paths, not both (signals caller confusion)."""
    from sim.inspect import SdkAttributeProbe

    with pytest.raises((ValueError, TypeError)):
        SdkAttributeProbe(
            attr_paths=["a.b"],
            readers=[("x", lambda s: 1)],
        )


def test_sdk_attribute_probe_old_attr_paths_call_still_works():
    """Regression: Phase 1 Fluent driver constructs with attr_paths=— must stay OK."""
    from sim.inspect import SdkAttributeProbe

    class _Chain:
        class _X:
            value = 42
        x = _X()

    p = SdkAttributeProbe(attr_paths=["x.value"])
    d = p.probe(_ctx(session_ns={"session": _Chain()})).diagnostics[0]
    assert "42" in d.message
    assert d.code == "fluent.sdk.attr.x.value"


# ── Channel 5 DomainExceptionMapProbe ──────────────────────────────────────────


def test_exception_map_probe_default_rules_are_empty():
    """Default rules must be empty: solver-specific exception→code mapping
    is a semantic judgement that belongs to the agent/skill layer, not the
    driver. DomainExceptionMapProbe remains available as a framework
    capability — callers pass rules explicitly when they want them."""
    from sim.inspect import Diagnostic, DomainExceptionMapProbe

    prior = [Diagnostic(
        severity="error",
        message="'velocity_inlet' has no attribute 'inlet'.",
        source="traceback",
        code="python.KeyError",
    )]
    r = DomainExceptionMapProbe().probe(
        _ctx(extras={"prior_diagnostics": prior})
    )
    assert r.diagnostics == [], (
        "DomainExceptionMapProbe() with no explicit rules must not emit "
        "any diagnostics — the default rule set is intentionally empty."
    )


def test_exception_map_probe_applies_explicit_rules():
    """When the caller passes rules explicitly, the probe must apply them.
    This guards the class's capability without wiring solver-specific
    rules into the driver layer."""
    from sim.inspect import Diagnostic, DomainExceptionMapProbe

    rules = [
        {
            "code_in": ("python.KeyError", "python.AttributeError"),
            "regex": r"has no attribute '([^']+)'",
            "upgrade_code": "fluent.sdk.attr_not_found",
            "message_template": "attr not found: '{group1}'",
        },
        {
            "code_in": ("python.RuntimeError",),
            "regex": r"Value is not allowed",
            "upgrade_code": "fluent.sdk.value_not_allowed",
            "message_template": "value rejected",
        },
    ]
    prior = [
        Diagnostic(severity="error",
                   message="'velocity_inlet' has no attribute 'inlet'.",
                   source="traceback", code="python.KeyError"),
        Diagnostic(severity="error", message="Value is not allowed",
                   source="traceback", code="python.RuntimeError"),
    ]
    r = DomainExceptionMapProbe(rules=rules).probe(
        _ctx(extras={"prior_diagnostics": prior})
    )
    codes = [d.code for d in r.diagnostics]
    assert "fluent.sdk.attr_not_found" in codes
    assert "fluent.sdk.value_not_allowed" in codes


def test_exception_map_probe_no_prior_no_output():
    from sim.inspect import DomainExceptionMapProbe

    r = DomainExceptionMapProbe().probe(_ctx())
    assert r.diagnostics == []


def test_exception_map_probe_ignores_non_matching():
    from sim.inspect import Diagnostic, DomainExceptionMapProbe

    prior = [Diagnostic(severity="error", message="totally unrelated",
                        source="traceback", code="python.OSError")]
    r = DomainExceptionMapProbe().probe(_ctx(extras={"prior_diagnostics": prior}))
    assert r.diagnostics == []


# ── Channel 9 WorkdirDiffProbe ─────────────────────────────────────────────────


def test_workdir_diff_probe_detects_new_files(tmp_path):
    from sim.inspect import WorkdirDiffProbe

    # Before: just the dir
    before = []
    (tmp_path / "a.cas.h5").write_bytes(b"x")
    (tmp_path / "a.dat.h5").write_bytes(b"y")
    (tmp_path / "session.trn").write_text("log content")

    ctx = _ctx(workdir=str(tmp_path), workdir_before=before)
    r = WorkdirDiffProbe(workdir_getter=lambda c: c.workdir).probe(ctx)
    roles = sorted(a.role for a in r.artifacts)
    assert "case" in roles
    assert "data" in roles
    assert "transcript" in roles
    assert len(r.artifacts) == 3


def test_workdir_diff_probe_ignores_pre_existing(tmp_path):
    from sim.inspect import WorkdirDiffProbe

    (tmp_path / "pre.cas.h5").write_bytes(b"x")
    before = ["pre.cas.h5"]
    (tmp_path / "new.cas.h5").write_bytes(b"y")

    ctx = _ctx(workdir=str(tmp_path), workdir_before=before)
    r = WorkdirDiffProbe(workdir_getter=lambda c: c.workdir).probe(ctx)
    paths = [Path(a.path).name for a in r.artifacts]
    assert paths == ["new.cas.h5"]


def test_workdir_diff_probe_applies_gated_on_before():
    from sim.inspect import WorkdirDiffProbe

    p = WorkdirDiffProbe(workdir_getter=lambda c: c.workdir)
    assert p.applies(_ctx(workdir_before=None)) is False
    assert p.applies(_ctx(workdir_before=[])) is True


def test_workdir_diff_probe_default_role_for_unknown_ext(tmp_path):
    from sim.inspect import WorkdirDiffProbe

    (tmp_path / "some.weird").write_bytes(b"x")
    ctx = _ctx(workdir=str(tmp_path), workdir_before=[])
    r = WorkdirDiffProbe(workdir_getter=lambda c: c.workdir).probe(ctx)
    assert r.artifacts[0].role == "output"
