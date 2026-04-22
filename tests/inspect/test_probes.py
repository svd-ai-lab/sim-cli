"""L1 unit tests — the 3 baseline probes.

ProcessMetaProbe       : exit_code / wall_time_s -> Diagnostic(source="process")
TextStreamRulesProbe   : regex rules over any text stream (stderr / stdout / file)
PythonTracebackProbe   : detect + parse Python tracebacks (stderr + session error)
"""
from __future__ import annotations

import textwrap


def _ctx(**kw):
    from sim.inspect import InspectCtx

    defaults = dict(
        stdout="", stderr="", workdir="/tmp",
        wall_time_s=0.0, exit_code=0, driver_name="x", session_ns={},
    )
    defaults.update(kw)
    return InspectCtx(**defaults)


# ── ProcessMetaProbe ────────────────────────────────────────────────────────────


def test_process_meta_probe_emits_info_on_success():
    from sim.inspect import ProcessMetaProbe

    p = ProcessMetaProbe()
    ctx = _ctx(exit_code=0, wall_time_s=1.25)
    result = p.probe(ctx)
    assert len(result.diagnostics) == 1
    d = result.diagnostics[0]
    assert d.severity == "info"
    assert d.source == "process"
    assert d.code == "sim.process.exit_zero"
    assert "1.25" in d.message or "1.25s" in d.message


def test_process_meta_probe_emits_error_on_nonzero_exit():
    from sim.inspect import ProcessMetaProbe

    p = ProcessMetaProbe()
    ctx = _ctx(exit_code=137, wall_time_s=4.2)
    result = p.probe(ctx)
    errs = [d for d in result.diagnostics if d.severity == "error"]
    assert len(errs) == 1
    assert errs[0].source == "process"
    assert errs[0].code == "sim.process.exit_nonzero"
    assert "137" in errs[0].message


def test_process_meta_probe_applies_always():
    from sim.inspect import ProcessMetaProbe

    p = ProcessMetaProbe()
    assert p.applies(_ctx()) is True


# ── TextStreamRulesProbe ────────────────────────────────────────────────────────


_OPENFOAM_STYLE_RULES = [
    {"pattern": r"FOAM FATAL ERROR", "severity": "error",
     "code": "openfoam.fatal", "message_template": "OpenFOAM fatal error"},
    {"pattern": r"patch (\S+) .*not found", "severity": "error",
     "code": "openfoam.bc.patch_missing",
     "message_template": "patch {match} not found"},
]


def test_text_stream_rules_probe_matches_regex():
    from sim.inspect import TextStreamRulesProbe

    text = textwrap.dedent("""
        some prefix line
        FOAM FATAL ERROR : patch something wrong
        --> Cannot find patch inlet not found in mesh
    """).strip()

    p = TextStreamRulesProbe(
        source="log:log.simpleFoam",
        text_selector=lambda ctx: text,
        rules=_OPENFOAM_STYLE_RULES,
    )
    result = p.probe(_ctx())
    codes = [d.code for d in result.diagnostics]
    assert "openfoam.fatal" in codes
    # 2nd rule should fire — "patch inlet .*not found"
    assert any(d.code == "openfoam.bc.patch_missing" for d in result.diagnostics)


def test_text_stream_rules_probe_carries_line_number_in_extra():
    from sim.inspect import TextStreamRulesProbe

    text = "ok\nok\nFOAM FATAL ERROR : boom\nok"
    p = TextStreamRulesProbe(
        source="log:log.simpleFoam",
        text_selector=lambda ctx: text,
        rules=[{"pattern": r"FOAM FATAL ERROR", "severity": "error",
                "code": "openfoam.fatal"}],
    )
    d = p.probe(_ctx()).diagnostics[0]
    assert d.source == "log:log.simpleFoam"
    assert d.extra.get("line") == 3


def test_text_stream_rules_probe_source_label_preserved():
    from sim.inspect import TextStreamRulesProbe

    p = TextStreamRulesProbe(
        source="stderr",
        text_selector=lambda ctx: ctx.stderr,
        rules=[{"pattern": r"Error:", "severity": "error", "code": "generic.error"}],
    )
    ctx = _ctx(stderr="Error: boom happened")
    d = p.probe(ctx).diagnostics[0]
    assert d.source == "stderr"
    assert d.code == "generic.error"


def test_text_stream_rules_probe_no_match_returns_empty():
    from sim.inspect import TextStreamRulesProbe

    p = TextStreamRulesProbe(
        source="stderr",
        text_selector=lambda ctx: "all clear, nothing interesting",
        rules=[{"pattern": r"Error:", "severity": "error", "code": "generic.error"}],
    )
    assert p.probe(_ctx()).diagnostics == []


def test_text_stream_rules_probe_applies_only_when_selector_yields_text():
    from sim.inspect import TextStreamRulesProbe

    p = TextStreamRulesProbe(
        source="stderr",
        text_selector=lambda ctx: ctx.stderr,
        rules=[{"pattern": r"x", "severity": "info", "code": "x"}],
    )
    assert p.applies(_ctx(stderr="has text")) is True
    assert p.applies(_ctx(stderr="")) is False


def test_text_stream_rules_probe_message_template_default():
    """When no message_template given, use matched line (trimmed)."""
    from sim.inspect import TextStreamRulesProbe

    p = TextStreamRulesProbe(
        source="stderr",
        text_selector=lambda ctx: "prefix\nboom: bad thing happened here\nsuffix",
        rules=[{"pattern": r"boom:", "severity": "error", "code": "x"}],
    )
    d = p.probe(_ctx()).diagnostics[0]
    assert "boom: bad thing" in d.message


def test_text_stream_rules_probe_template_with_match_group():
    from sim.inspect import TextStreamRulesProbe

    p = TextStreamRulesProbe(
        source="stderr",
        text_selector=lambda ctx: "boundary 'cold-inlet' not found in BC set",
        rules=[{
            "pattern": r"boundary '(\S+)' not found",
            "severity": "error", "code": "fluent.bc.missing",
            "message_template": "BC {group1} not found",
        }],
    )
    d = p.probe(_ctx()).diagnostics[0]
    assert d.message == "BC cold-inlet not found"


# ── PythonTracebackProbe ───────────────────────────────────────────────────────


_SAMPLE_TRACEBACK = textwrap.dedent('''
    Traceback (most recent call last):
      File "<string>", line 3, in <module>
      File "/tmp/foo.py", line 10, in some_fn
        raise NameError("name 'undefined_name' is not defined")
    NameError: name 'undefined_name' is not defined
''').strip()


def test_traceback_probe_detects_python_exception_in_stderr():
    from sim.inspect import PythonTracebackProbe

    p = PythonTracebackProbe()
    ctx = _ctx(stderr=_SAMPLE_TRACEBACK)
    result = p.probe(ctx)
    errs = [d for d in result.diagnostics if d.severity == "error"]
    assert len(errs) >= 1
    d = errs[0]
    assert d.source == "traceback"
    assert d.code == "python.NameError"
    assert "undefined_name" in d.message


def test_traceback_probe_reads_session_error_field_too():
    """Session exec captures traceback into session_ns['_session_error']."""
    from sim.inspect import PythonTracebackProbe

    p = PythonTracebackProbe()
    ctx = _ctx(
        session_ns={"_session_error": _SAMPLE_TRACEBACK},
    )
    result = p.probe(ctx)
    errs = [d for d in result.diagnostics if d.severity == "error"]
    assert len(errs) >= 1
    assert errs[0].code == "python.NameError"


def test_traceback_probe_no_traceback_returns_empty():
    from sim.inspect import PythonTracebackProbe

    p = PythonTracebackProbe()
    ctx = _ctx(stderr="just some warnings, no traceback here")
    assert p.probe(ctx).diagnostics == []


def test_traceback_probe_handles_valueerror():
    from sim.inspect import PythonTracebackProbe

    tb = textwrap.dedent('''
        Traceback (most recent call last):
          File "<string>", line 1, in <module>
        ValueError: invalid literal for int() with base 10: 'abc'
    ''').strip()
    p = PythonTracebackProbe()
    d = p.probe(_ctx(stderr=tb)).diagnostics[0]
    assert d.code == "python.ValueError"
    assert "invalid literal" in d.message


def test_traceback_probe_applies_when_any_signal():
    from sim.inspect import PythonTracebackProbe

    p = PythonTracebackProbe()
    assert p.applies(_ctx(stderr=_SAMPLE_TRACEBACK)) is True
    assert p.applies(_ctx(session_ns={"_session_error": _SAMPLE_TRACEBACK})) is True
    # applies() only fires when the header is actually present
    assert p.applies(_ctx(stderr="no traceback header here")) is False
    assert p.applies(_ctx()) is False
