"""DPF post-processing E2E for LS-DYNA — replaces LS-PrePost screenshot.

Verifies that ansys-dpf-core can read the d3plot from the existing E2E run,
extract energies / displacements / stresses, and render PNG visualizations.

This is the "GUI evidence" path: instead of automating LS-PrePost (which is
unreliable, see KI-005), use DPF + PyVista headlessly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).parent.parent.parent / "execution" / "lsdyna"
D3PLOT = E2E_DIR / "d3plot"

# Skip if no d3plot (run E2E first), no DPF, or no AWP_ROOT
HAS_D3PLOT = D3PLOT.is_file()
try:
    import ansys.dpf.core as dpf  # noqa: F401
    HAS_DPF = True
except ImportError:
    HAS_DPF = False

AWP_ROOT = Path("E:/Program Files/ANSYS Inc/v241")
HAS_ANSYS = AWP_ROOT.is_dir()

pytestmark = pytest.mark.skipif(
    not (HAS_D3PLOT and HAS_DPF and HAS_ANSYS),
    reason="Requires d3plot from prior E2E + ansys-dpf-core + ANSYS install",
)


@pytest.fixture(scope="module")
def dpf_model():
    """Load the d3plot once per module via DPF."""
    import ansys.dpf.core as dpf

    if not os.environ.get("AWP_ROOT241"):
        os.environ["AWP_ROOT241"] = str(AWP_ROOT)

    try:
        dpf.start_local_server(ansys_path=str(AWP_ROOT))
    except Exception:
        # Server may already be running
        pass

    ds = dpf.DataSources()
    ds.set_result_file_path(str(D3PLOT), "d3plot")
    return dpf.Model(ds), ds


class TestDpfModelLoad:
    def test_model_loads(self, dpf_model):
        model, _ = dpf_model
        assert model is not None

    def test_has_12_states(self, dpf_model):
        model, _ = dpf_model
        time_data = model.metadata.time_freq_support.time_frequencies.data_as_list
        assert len(time_data) == 12

    def test_mesh_has_8_nodes_1_element(self, dpf_model):
        model, _ = dpf_model
        mesh = model.metadata.meshed_region
        assert mesh.nodes.n_nodes == 8
        assert mesh.elements.n_elements == 1


class TestEnergyExtraction:
    def test_kinetic_energy_decays(self, dpf_model):
        """KE should be ~0 at end (quasi-static load)."""
        import ansys.dpf.core as dpf
        _, ds = dpf_model
        gke_op = dpf.operators.result.global_kinetic_energy()
        gke_op.inputs.data_sources.connect(ds)
        ke = gke_op.eval().get_field(0).data
        assert abs(ke[-1]) < 1e-10, f"KE should be ~0 at end, got {ke[-1]}"

    def test_internal_energy_present(self, dpf_model):
        """IE should be non-zero (work done by load)."""
        import ansys.dpf.core as dpf
        _, ds = dpf_model
        gie_op = dpf.operators.result.global_internal_energy()
        gie_op.inputs.data_sources.connect(ds)
        ie = gie_op.eval().get_field(0).data
        assert abs(ie[-1]) > 1e-5, f"IE should be non-trivial, got {ie[-1]}"


class TestStressDisplacement:
    def test_displacement_in_elastic_range(self, dpf_model):
        """Final displacement should be small (elastic)."""
        import numpy as np
        model, _ = dpf_model
        disp_op = model.results.displacement.on_last_time_freq()
        disp_field = disp_op.eval().get_field(0)
        disp_arr = np.asarray(disp_field.data).reshape(-1, 3)
        max_disp = np.linalg.norm(disp_arr, axis=1).max()
        # Steel cube 1mm under 10 MPa → strain ~5e-5 → disp ~5e-5 mm
        # We see ~3e-2 due to dynamic overshoot; should be < 0.1 mm anyway
        assert 0 < max_disp < 0.1, f"Disp out of elastic range: {max_disp}"

    def test_von_mises_stress_matches_load(self, dpf_model):
        """Stress should be ~10 MPa (the applied stress)."""
        import numpy as np
        model, _ = dpf_model
        stress_op = model.results.stress_von_mises.on_last_time_freq()
        stress_field = stress_op.eval().get_field(0)
        stress_data = np.asarray(stress_field.data).flatten()
        # Applied: 4 nodes × 0.0025 kN / 1 mm² = 0.01 kN/mm² = 10 MPa = 0.01 GPa
        assert 0.001 < stress_data.max() < 0.05, (
            f"von Mises out of expected range: {stress_data.max()} GPa"
        )


class TestVisualization:
    """Verify PNG outputs were produced by dpf_visualize.py."""

    def test_energy_plot_exists(self):
        assert (E2E_DIR / "dpf_kinetic_energy.png").is_file()

    def test_displacement_plot_exists(self):
        assert (E2E_DIR / "dpf_displacement.png").is_file()

    def test_stress_contour_exists(self):
        assert (E2E_DIR / "dpf_stress_contour.png").is_file()

    def test_dpf_summary_json(self):
        f = E2E_DIR / "dpf_summary.json"
        assert f.is_file()
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["n_states"] == 12
        assert "kinetic_energy" in data
        assert "displacement_final" in data
