"""L1 unit tests — core inspect types and collect_diagnostics loop.

Pure unit tests, zero Fluent dependency. Covers §三 字面 schema:
- Diagnostic: severity / message / source / code / extra
- Artifact:   path / size / mtime / role
- InspectCtx: input bundle passed to every probe
- ProbeResult: what a probe returns
- InspectProbe: Protocol
- collect_diagnostics(probes, ctx) -> (diagnostics, artifacts)
"""
from __future__ import annotations

import pytest


# ── schema smoke ────────────────────────────────────────────────────────────────

def test_diagnostic_has_spec_fields():
    from sim.inspect import Diagnostic

    d = Diagnostic(
        severity="error",
        message="BC missing on patch 'inlet' for field 'U'",
        source="log:log.simpleFoam",
        code="openfoam.bc.missing",
    )
    out = d.to_dict()
    assert set(out.keys()) >= {"severity", "message", "source", "code", "extra"}
    assert out["severity"] == "error"
    assert out["source"] == "log:log.simpleFoam"
    assert out["code"] == "openfoam.bc.missing"
    assert out["extra"] == {}


def test_diagnostic_extra_is_escape_hatch():
    from sim.inspect import Diagnostic

    d = Diagnostic(
        severity="error", message="m", source="log:x",
        extra={"line": 42, "file": "log.simpleFoam"},
    )
    assert d.to_dict()["extra"]["line"] == 42


def test_artifact_has_spec_fields():
    from sim.inspect import Artifact

    a = Artifact(path="run.out", size=34521, mtime="2026-04-22T00:00:00Z",
                 role="solver-log")
    out = a.to_dict()
    assert set(out.keys()) >= {"path", "size", "mtime", "role"}
    assert out["path"] == "run.out"
    assert out["role"] == "solver-log"


def test_probe_result_empty_default():
    from sim.inspect import ProbeResult

    r = ProbeResult()
    assert r.diagnostics == []
    assert r.artifacts == []
    assert r.raw == {}


def test_inspect_ctx_shape():
    from sim.inspect import InspectCtx

    ctx = InspectCtx(
        stdout="", stderr="", workdir="/tmp",
        wall_time_s=0.0, exit_code=0, driver_name="fluent",
        session_ns={"session": None},
    )
    assert ctx.exit_code == 0
    assert ctx.driver_name == "fluent"
    assert ctx.session_ns == {"session": None}


# ── collect_diagnostics behavior ────────────────────────────────────────────────

class _FakeProbe:
    """Minimal InspectProbe stub for exercising collect_diagnostics()."""

    def __init__(self, name, diags=None, arts=None, applies=True, raises=False):
        self.name = name
        self._diags = diags or []
        self._arts = arts or []
        self._applies = applies
        self._raises = raises

    def applies(self, ctx):
        return self._applies

    def probe(self, ctx):
        from sim.inspect import ProbeResult
        if self._raises:
            raise RuntimeError("boom from probe")
        return ProbeResult(diagnostics=list(self._diags), artifacts=list(self._arts))


def _ctx():
    from sim.inspect import InspectCtx
    return InspectCtx(
        stdout="", stderr="", workdir="/tmp",
        wall_time_s=0.0, exit_code=0, driver_name="x", session_ns={},
    )


def test_collect_concatenates_in_probe_order():
    from sim.inspect import Diagnostic, collect_diagnostics

    d1 = Diagnostic(severity="info", message="m1", source="a", code="c1")
    d2 = Diagnostic(severity="error", message="m2", source="b", code="c2")
    p1 = _FakeProbe("a", diags=[d1])
    p2 = _FakeProbe("b", diags=[d2])

    diags, arts = collect_diagnostics([p1, p2], _ctx())
    assert [d.code for d in diags] == ["c1", "c2"]
    assert arts == []


def test_collect_skips_non_applicable():
    from sim.inspect import Diagnostic, collect_diagnostics

    d = Diagnostic(severity="info", message="m", source="s", code="c")
    skip = _FakeProbe("skip", diags=[d], applies=False)

    diags, _ = collect_diagnostics([skip], _ctx())
    assert diags == []


def test_collect_isolates_probe_exceptions():
    """A crashing probe must NOT abort collection; it should emit a synthetic diag."""
    from sim.inspect import Diagnostic, collect_diagnostics

    d_ok = Diagnostic(severity="info", message="m", source="ok", code="c1")
    p_ok = _FakeProbe("ok", diags=[d_ok])
    p_bad = _FakeProbe("bad", raises=True)

    diags, _ = collect_diagnostics([p_bad, p_ok], _ctx())
    # Expect: 1 synthetic from p_bad + 1 real from p_ok
    assert len(diags) == 2
    crashed = [d for d in diags if d.code == "sim.inspect.probe_crashed"]
    assert len(crashed) == 1
    assert "bad" in crashed[0].message
    assert "boom from probe" in crashed[0].message


def test_collect_returns_artifacts_too():
    from sim.inspect import Artifact, collect_diagnostics

    a = Artifact(path="out.cas.h5", role="case")
    p = _FakeProbe("a", arts=[a])

    diags, arts = collect_diagnostics([p], _ctx())
    assert diags == []
    assert [x.path for x in arts] == ["out.cas.h5"]


def test_inspect_probe_protocol_is_runtime_checkable():
    from sim.inspect import InspectProbe

    p = _FakeProbe("x")
    # runtime_checkable Protocol should accept our duck-typed probe
    assert isinstance(p, InspectProbe)
