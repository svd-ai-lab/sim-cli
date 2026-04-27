"""Integration tests for Fluent via sim-server.

Run against a live sim-server with Fluent available:

    # On win1 (RDP):
    sim serve --host 0.0.0.0

    # On Mac:
    pytest tests/test_integration.py \
        --sim-host=100.90.110.79 --mesh-file='/path/to/mixing_elbow.msh.h5'

Skipped by default unless --sim-host is provided.
"""
from __future__ import annotations

import pytest
import httpx


@pytest.fixture(scope="module")
def server(request):
    host = request.config.getoption("--sim-host")
    if not host:
        pytest.skip("--sim-host not provided")
    port = request.config.getoption("--sim-port")
    return f"http://{host}:{port}"


@pytest.fixture(scope="module")
def mesh_file(request):
    return request.config.getoption("--mesh-file")


@pytest.fixture(scope="module")
def solver_session(server):
    """Connect a solver session, yield the client, disconnect on teardown."""
    c = httpx.Client(base_url=server, timeout=180)

    # Disconnect any stale session
    c.post("/disconnect")

    r = c.post("/connect", json={
        "solver": "fluent", "mode": "solver",
        "ui_mode": "gui", "processors": 2,
    })
    assert r.status_code == 200, f"connect failed: {r.text}"
    data = r.json()
    assert data["ok"], f"connect not ok: {data}"

    yield c

    c.post("/disconnect")
    c.close()


class TestSolverWorkflow:
    """Full mixing elbow workflow: load → physics → BCs → init → solve → extract."""

    def test_01_ps(self, solver_session):
        r = solver_session.get("/ps")
        data = r.json()
        assert data["connected"]
        assert data["mode"] == "solver"

    def test_02_read_mesh(self, solver_session, mesh_file):
        r = solver_session.post("/exec", json={
            "code": f"""
import os
MESH_FILE = r'{mesh_file}'
assert os.path.isfile(MESH_FILE), f'not found: {{MESH_FILE}}'
solver.settings.file.read_case(file_name=MESH_FILE)
_result = {{'ok': True}}
""",
            "label": "read-mesh",
        })
        data = r.json()
        assert data["ok"], f"read-mesh failed: {data}"
        assert data["data"]["result"]["ok"]

    def test_03_setup_physics(self, solver_session):
        r = solver_session.post("/exec", json={
            "code": """
solver.settings.setup.models.energy.enabled = True
v = solver.settings.setup.models.viscous
v.model = 'k-epsilon'
v.k_epsilon_model = 'realizable'
_result = {'ok': True}
""",
            "label": "setup-physics",
        })
        assert r.json()["ok"]

    def test_04_setup_material(self, solver_session):
        r = solver_session.post("/exec", json={
            "code": """
solver.settings.setup.materials.database.copy_by_name(type='fluid', name='water-liquid')
zones = list(solver.settings.setup.cell_zone_conditions.fluid.keys())
solver.settings.setup.cell_zone_conditions.fluid[zones[0]].general.material = 'water-liquid'
_result = {'zone': zones[0], 'ok': True}
""",
            "label": "setup-material",
        })
        assert r.json()["ok"]

    def test_05_setup_bcs(self, solver_session):
        r = solver_session.post("/exec", json={
            "code": """
cold = solver.settings.setup.boundary_conditions.velocity_inlet['cold-inlet']
cold.momentum.velocity_magnitude.value = 0.4
cold.turbulence.turbulent_specification = 'Intensity and Hydraulic Diameter'
cold.turbulence.turbulent_intensity = 0.05
cold.turbulence.hydraulic_diameter = '4 [in]'
cold.thermal.temperature.value = 293.15

hot = solver.settings.setup.boundary_conditions.velocity_inlet['hot-inlet']
hot.momentum.velocity_magnitude.value = 1.2
hot.turbulence.turbulent_specification = 'Intensity and Hydraulic Diameter'
hot.turbulence.turbulent_intensity = 0.05
hot.turbulence.hydraulic_diameter = '1 [in]'
hot.thermal.temperature.value = 313.15

outlet = solver.settings.setup.boundary_conditions.pressure_outlet['outlet']
outlet.turbulence.turbulent_specification = 'Intensity and Viscosity Ratio'
outlet.turbulence.turbulent_intensity = 0.05
outlet.turbulence.backflow_turbulent_viscosity_ratio = 4
_result = {'ok': True}
""",
            "label": "setup-bcs",
        })
        assert r.json()["ok"]

    def test_06_hybrid_init(self, solver_session):
        r = solver_session.post("/exec", json={
            "code": """
solver.settings.solution.initialization.hybrid_initialize()
_result = {'ok': True}
""",
            "label": "hybrid-init",
        })
        assert r.json()["ok"]

    def test_07_solve(self, solver_session):
        r = solver_session.post("/exec", json={
            "code": """
solver.settings.solution.run_calculation.iterate(iter_count=150)
_result = {'ok': True}
""",
            "label": "solve-150",
        }, timeout=300)
        assert r.json()["ok"]

    def test_08_extract_temperature(self, solver_session):
        r = solver_session.post("/exec", json={
            "code": """
rep = solver.settings.solution.report_definitions
rep.surface['outlet-temp-avg'] = {}
rt = rep.surface['outlet-temp-avg']
rt.report_type = 'surface-areaavg'
rt.field = 'temperature'
rt.surface_names = ['outlet']
result = rep.compute(report_defs=['outlet-temp-avg'])
entry = result[0] if isinstance(result, list) else result
val = entry['outlet-temp-avg']
temp_K = float(val[0]) if isinstance(val, (list, tuple)) else float(val)
temp_C = round(temp_K - 273.15, 2)
_result = {'outlet_temp_K': temp_K, 'outlet_temp_C': temp_C, 'ok': True}
""",
            "label": "extract-temp",
        })
        data = r.json()
        assert data["ok"]
        temp_C = data["data"]["result"]["outlet_temp_C"]
        assert 20 < temp_C < 40, f"outlet temp {temp_C}°C outside expected range"

    def test_09_inspect_last(self, solver_session):
        r = solver_session.get("/inspect/last.result")
        data = r.json()["data"]
        assert data["has_last_run"]
        assert data["label"] == "extract-temp"
        assert data["ok"]

    def test_10_run_count(self, solver_session):
        r = solver_session.get("/ps")
        assert r.json()["run_count"] == 7
