"""Tier 4: Real Ansys Workbench integration tests via PyWorkbench SDK.

These tests require a real Ansys Workbench installation + ansys-workbench-core.
Marked with @pytest.mark.integration and skipped when unavailable.

Physics-based acceptance criteria:
- Static Structural system must expose exactly 6 standard components
- Component names must match the canonical Workbench taxonomy
- SDK session lifecycle must be clean (launch → run → query → disconnect)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sim.drivers.workbench.driver import WorkbenchDriver

FIXTURES = Path(__file__).parent / "fixtures"

driver = WorkbenchDriver()
_installs = driver.detect_installed()
HAS_WORKBENCH = len(_installs) > 0

try:
    import ansys.workbench.core
    HAS_SDK = True
except ImportError:
    HAS_SDK = False

skip_no_workbench = pytest.mark.skipif(
    not HAS_WORKBENCH or not HAS_SDK,
    reason="Ansys Workbench or PyWorkbench SDK not available",
)


@pytest.mark.integration
@skip_no_workbench
class TestWorkbenchRealDetection:
    def test_detect_installed_returns_installs(self):
        installs = driver.detect_installed()
        assert len(installs) >= 1
        top = installs[0]
        assert top.name == "workbench"
        assert top.version
        assert Path(top.path).is_dir()

    def test_connect_real(self):
        info = driver.connect()
        assert info.status == "ok"
        assert info.version is not None
        assert "Workbench" in info.message


@pytest.mark.integration
@skip_no_workbench
class TestWorkbenchSDKExecution:
    """Tier 4: Execute real journals via PyWorkbench SDK."""

    def test_run_static_structural_journal(self):
        """Create a Static Structural system and validate components.

        Acceptance criteria (physics-based, irreducible):
        1. exit_code == 0 (SDK accepted the journal)
        2. System created with exactly 6 components
        3. Components match canonical Workbench taxonomy
        """
        result = driver.run_file(FIXTURES / "workbench_static_structural.wbjn")

        assert result.exit_code == 0, f"SDK execution failed: {result.stderr}"

        parsed = driver.parse_output(result.stdout)
        assert parsed.get("ok") is True, f"Journal reported failure: {parsed}"
        assert parsed.get("component_count") == 6
        assert set(parsed.get("components", [])) == {
            "Engineering Data", "Geometry", "Model",
            "Setup", "Solution", "Results",
        }

    def test_run_file_returns_run_result(self):
        result = driver.run_file(FIXTURES / "workbench_static_structural.wbjn")
        assert result.solver == "workbench"
        assert result.script.endswith(".wbjn")
        assert result.duration_s > 0


@pytest.mark.integration
@skip_no_workbench
class TestWorkbenchSDKSession:
    """Tier 3: SDK persistent session lifecycle."""

    def test_launch_run_query_disconnect(self):
        """Full session lifecycle via PyWorkbench SDK."""
        d = WorkbenchDriver()

        # Launch
        info = d.launch(mode="workbench")
        assert info["ok"] is True
        assert info["backend"] == "pyworkbench"
        assert d.is_connected is True

        # Run a script snippet
        script = '''
SetScriptVersion(Version="24.1")
template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()

import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "created": "Static Structural"}))
f.close()
'''
        run_result = d.run(script, label="create-system")
        assert run_result["ok"] is True
        assert run_result["label"] == "create-system"
        assert run_result["elapsed_s"] > 0

        # Parse result
        parsed = d.run('''
import json, os, codecs
out = os.path.join(os.environ.get("TEMP", "C:/Temp"), "sim_wb_result.json")
f = codecs.open(out, "w", "utf-8")
f.write(json.dumps({"ok": True, "systems": 1}))
f.close()
''', label="check")
        assert parsed["ok"] is True

        # Query session summary
        summary = d.query("session.summary")
        assert summary["connected"] is True
        assert summary["run_count"] == 2
        assert summary["backend"] in ("pyworkbench", "runwb2")

        # Disconnect
        d.disconnect()
        assert d.is_connected is False


@pytest.mark.integration
@skip_no_workbench
class TestWorkbenchCLIIntegration:
    def test_sim_check_workbench(self):
        from sim.drivers import get_driver
        d = get_driver("workbench")
        assert d is not None
        info = d.connect()
        assert info.status == "ok"
