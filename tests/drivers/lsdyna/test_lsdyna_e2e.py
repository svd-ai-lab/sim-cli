"""E2E tests for LS-DYNA driver — requires real LS-DYNA installation.

Test case: single hex element under uniaxial tension (explicit dynamics).
- 1x1x1 mm cube, steel (*MAT_ELASTIC), bottom face fixed, top face loaded
- 7129 cycles to t=1.0 ms, normal termination in ~1s
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from sim.drivers.lsdyna import LsDynaDriver

# The E2E keyword file lives next to execution scripts
E2E_DIR = Path(__file__).parent.parent.parent / "execution" / "lsdyna"
K_FILE = E2E_DIR / "single_hex_tension.k"

driver = LsDynaDriver()

# Skip entire module if LS-DYNA not installed
HAS_LSDYNA = bool(driver.detect_installed())
pytestmark = pytest.mark.skipif(not HAS_LSDYNA, reason="LS-DYNA not installed")


@pytest.fixture(scope="module")
def run_result():
    """Run the single-hex tension test once, share the result across tests."""
    assert K_FILE.is_file(), f"E2E keyword file not found: {K_FILE}"

    # Clean up any previous output files in the working directory
    for f in E2E_DIR.glob("d3*"):
        f.unlink(missing_ok=True)
    for f in E2E_DIR.glob("glstat"):
        f.unlink(missing_ok=True)
    for f in E2E_DIR.glob("messag"):
        f.unlink(missing_ok=True)
    for f in E2E_DIR.glob("status.out"):
        f.unlink(missing_ok=True)

    result = driver.run_file(K_FILE)
    return result


class TestSolveCompletes:
    def test_exit_code_zero(self, run_result):
        assert run_result.exit_code == 0

    def test_normal_termination(self, run_result):
        """LS-DYNA prints 'N o r m a l    t e r m i n a t i o n' on success."""
        combined = run_result.stdout + run_result.stderr
        assert re.search(
            r"N\s*o\s*r\s*m\s*a\s*l\s+t\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*i\s*o\s*n",
            combined,
        ), f"Normal termination not found in output"

    def test_no_error_termination(self, run_result):
        combined = run_result.stdout + run_result.stderr
        assert not re.search(
            r"E\s*r\s*r\s*o\s*r\s+t\s*e\s*r\s*m\s*i\s*n\s*a\s*t\s*i\s*o\s*n",
            combined,
        ), "Error termination detected"


class TestOutputFiles:
    def test_d3plot_produced(self, run_result):
        """d3plot is the primary visualization output."""
        assert (E2E_DIR / "d3plot").is_file()

    def test_d3hsp_produced(self, run_result):
        """d3hsp contains detailed solver output."""
        assert (E2E_DIR / "d3hsp").is_file()

    def test_glstat_produced(self, run_result):
        """glstat contains global statistics (energies, timestep)."""
        assert (E2E_DIR / "glstat").is_file()

    def test_messag_produced(self, run_result):
        """messag contains solver messages."""
        assert (E2E_DIR / "messag").is_file()


class TestPhysicsValidation:
    def test_cycles_completed(self, run_result):
        """Should complete ~7000+ cycles for t=1.0ms explicit."""
        m = re.search(r"Problem cycle\s*=\s*(\d+)", run_result.stdout)
        assert m, "Could not find cycle count in output"
        cycles = int(m.group(1))
        assert cycles > 5000, f"Too few cycles: {cycles}"

    def test_termination_time_reached(self, run_result):
        """Should reach the target end time of 1.0."""
        assert "termination time reached" in run_result.stdout


class TestParseOutput:
    def test_parsed_output_has_termination(self, run_result):
        parsed = driver.parse_output(run_result.stdout)
        assert parsed.get("termination") == "normal"


class TestEvidenceSaved:
    """Save E2E evidence for the skill."""

    def test_save_summary(self, run_result):
        """Write an E2E summary JSON for skill evidence."""
        m_cycles = re.search(r"Problem cycle\s*=\s*(\d+)", run_result.stdout)
        m_time = re.search(r"Problem time\s*=\s*([\d.E+-]+)", run_result.stdout)

        summary = {
            "test_case": "single_hex_tension",
            "solver": "LS-DYNA R14.0 smp s",
            "exit_code": run_result.exit_code,
            "duration_s": run_result.duration_s,
            "cycles": int(m_cycles.group(1)) if m_cycles else None,
            "problem_time": m_time.group(1) if m_time else None,
            "termination": "normal",
            "output_files": [
                f.name for f in E2E_DIR.iterdir()
                if not f.name.endswith(".k") and not f.name.endswith(".py") and not f.name.endswith(".json") and f.is_file()
            ],
        }

        evidence_path = E2E_DIR / "e2e_summary.json"
        evidence_path.write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        assert evidence_path.is_file()
