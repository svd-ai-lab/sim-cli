"""Tests for Flotherm FloSCRIPT and FloXML linting."""
from pathlib import Path
import textwrap

import pytest

from sim.drivers.flotherm._helpers import lint_floscript, lint_floxml
from sim.drivers.flotherm.driver import FlothermDriver

# XSD schemas in sim-skills (may not be available in CI)
_SCHEMA_DIR = (
    Path(__file__).resolve().parents[3]
    / ".." / "sim-skills" / "flotherm" / "base" / "reference"
    / "flotherm" / "2504" / "examples" / "floscript" / "schema"
)
_HAS_SCHEMA = _SCHEMA_DIR.is_dir()

needs_schema = pytest.mark.skipif(
    not _HAS_SCHEMA, reason="sim-skills XSD schemas not available"
)


def _write_xml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.xml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ── Basic validation (no schema) ──────────────────────────────────────


class TestBasicLint:
    def test_empty_file(self, tmp_path):
        p = _write_xml(tmp_path, "")
        result = lint_floscript(p)
        assert result.ok is False
        assert "empty" in result.diagnostics[0].message.lower()

    def test_invalid_xml(self, tmp_path):
        p = _write_xml(tmp_path, "<not closed")
        result = lint_floscript(p)
        assert result.ok is False
        assert "xml parse error" in result.diagnostics[0].message.lower()

    def test_wrong_root(self, tmp_path):
        p = _write_xml(tmp_path, '<xml_case version="1.0"/>')
        result = lint_floscript(p)
        assert result.ok is False
        assert "xml_log_file" in result.diagnostics[0].message

    def test_valid_with_solve(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <start start_type="solver"/>
            </xml_log_file>
        """)
        result = lint_floscript(p)
        assert result.ok is True
        assert not any(d.level == "error" for d in result.diagnostics)

    def test_no_solve_warns_by_default(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <create_geometry geometry_type="cuboid">
                <source_geometry><geometry name="Root Assembly"/></source_geometry>
              </create_geometry>
            </xml_log_file>
        """)
        result = lint_floscript(p)
        assert result.ok is True
        warnings = [d for d in result.diagnostics if d.level == "warning"]
        assert any("solve" in w.message.lower() for w in warnings)

    def test_no_solve_suppressed(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <create_geometry geometry_type="cuboid">
                <source_geometry><geometry name="Root Assembly"/></source_geometry>
              </create_geometry>
            </xml_log_file>
        """)
        result = lint_floscript(p, require_solve=False)
        assert result.ok is True
        assert not any("solve" in d.message.lower() for d in result.diagnostics)


# ── XSD validation ────────────────────────────────────────────────────


class TestXSDValidation:
    @needs_schema
    def test_valid_script_passes(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <create_geometry geometry_type="cuboid">
                <source_geometry><geometry name="Root Assembly"/></source_geometry>
              </create_geometry>
              <start start_type="solver"/>
            </xml_log_file>
        """)
        result = lint_floscript(p, schema_dir=_SCHEMA_DIR)
        assert result.ok is True
        assert not any(d.level == "error" for d in result.diagnostics)

    @needs_schema
    def test_unknown_command_fails(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <bogus_command/>
            </xml_log_file>
        """)
        result = lint_floscript(p, schema_dir=_SCHEMA_DIR)
        assert result.ok is False
        errors = [d for d in result.diagnostics if d.level == "error"]
        assert len(errors) >= 1
        assert "line" in errors[0].message.lower()

    @needs_schema
    def test_invalid_geometry_type_fails(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <create_geometry geometry_type="nonexistent_type">
                <source_geometry><geometry name="Root Assembly"/></source_geometry>
              </create_geometry>
            </xml_log_file>
        """)
        result = lint_floscript(p, schema_dir=_SCHEMA_DIR)
        assert result.ok is False
        errors = [d for d in result.diagnostics if d.level == "error"]
        assert len(errors) >= 1

    @needs_schema
    def test_model_building_no_solve(self, tmp_path):
        """Model-building script with require_solve=False should pass XSD."""
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <create_geometry geometry_type="cuboid">
                <source_geometry><geometry name="Root Assembly"/></source_geometry>
              </create_geometry>
              <project_save_as project_name="test" project_title="Test"/>
            </xml_log_file>
        """)
        result = lint_floscript(p, schema_dir=_SCHEMA_DIR, require_solve=False)
        assert result.ok is True
        assert not any(d.level == "error" for d in result.diagnostics)

    @needs_schema
    def test_error_has_line_number(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <start start_type="solver"/>
              <fake_element/>
            </xml_log_file>
        """)
        result = lint_floscript(p, schema_dir=_SCHEMA_DIR)
        assert result.ok is False
        errors = [d for d in result.diagnostics if d.level == "error"]
        assert any("Line " in d.message for d in errors)

    def test_missing_schema_dir_warns(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <start start_type="solver"/>
            </xml_log_file>
        """)
        result = lint_floscript(p, schema_dir=tmp_path / "nonexistent")
        assert result.ok is True
        warnings = [d for d in result.diagnostics if d.level == "warning"]
        assert any("xsd" in w.message.lower() for w in warnings)

    def test_no_schema_dir_basic_only(self, tmp_path):
        """Without schema_dir, only basic checks run (existing behavior)."""
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <bogus_command/>
              <start start_type="solver"/>
            </xml_log_file>
        """)
        # bogus_command won't be caught without XSD
        result = lint_floscript(p, schema_dir=None)
        assert result.ok is True


# ── FloXML linting ──────────────────────────────────────────────────


class TestFloxmlLint:
    def test_xml_case_minimal(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0" encoding="UTF-8" standalone="no"?>
            <xml_case>
              <name>HBM_demo</name>
            </xml_case>
        """)
        result = lint_floxml(p)
        assert result.ok is True

    def test_sm_xml_case_minimal(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <sm_xml_case>
              <name>SmartPart</name>
            </sm_xml_case>
        """)
        result = lint_floxml(p)
        assert result.ok is True

    def test_wrong_root(self, tmp_path):
        p = _write_xml(tmp_path, "<not_floxml/>")
        result = lint_floxml(p)
        assert result.ok is False
        assert "xml_case" in result.diagnostics[0].message

    def test_empty_file(self, tmp_path):
        p = _write_xml(tmp_path, "")
        result = lint_floxml(p)
        assert result.ok is False

    def test_invalid_xml(self, tmp_path):
        p = _write_xml(tmp_path, "<xml_case><not closed")
        result = lint_floxml(p)
        assert result.ok is False


class TestDriverLintRouting:
    """`FlothermDriver.lint` must dispatch FloSCRIPT vs FloXML by root tag."""

    def test_routes_floscript(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_log_file version="1.0">
              <start start_type="solver"/>
            </xml_log_file>
        """)
        result = FlothermDriver().lint(p)
        assert result.ok is True

    def test_routes_floxml(self, tmp_path):
        p = _write_xml(tmp_path, """\
            <?xml version="1.0"?>
            <xml_case>
              <name>X</name>
            </xml_case>
        """)
        result = FlothermDriver().lint(p)
        assert result.ok is True
