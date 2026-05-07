"""Optional real-Fluent integration smoke for the bundled live-session path."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


EX01_STEPS = [
    ("mesh-check", "02_mesh_check.py"),
    ("setup-physics", "03_setup_physics.py"),
    ("setup-material", "04_setup_material.py"),
    ("setup-bcs", "05a_setup_bcs_ex01_ex05.py"),
    ("hybrid-init", "06_hybrid_init.py"),
    ("run-iterations", "07_run_150_iter.py"),
    ("extract-temp", "08a_extract_outlet_temp.py"),
]


def _have_pyfluent() -> bool:
    try:
        import ansys.fluent.core  # noqa: F401

        return True
    except Exception:
        return False


def _mixing_elbow_case() -> Path | None:
    raw = os.environ.get("SIM_FLUENT_CASE")
    if raw:
        path = Path(raw)
        return path if path.is_file() else None
    try:
        from ansys.fluent.core.examples import download_file  # noqa: PLC0415

        path = Path(download_file("mixing_elbow.cas.h5", "pyfluent/mixing_elbow"))
    except Exception:
        return None
    return path if path.is_file() else None


def _resolve_snippet(
    fluent_root: Path,
    active_sdk_layer: str | None,
    active_solver_layer: str | None,
    name: str,
) -> Path:
    candidates: list[Path] = []
    if active_solver_layer:
        candidates.append(fluent_root / "solver" / active_solver_layer / "snippets" / name)
    if active_sdk_layer:
        candidates.append(fluent_root / "sdk" / active_sdk_layer / "snippets" / name)
    candidates.append(fluent_root / "base" / "snippets" / name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"snippet {name!r} not found under {fluent_root}")


@pytest.fixture(scope="module")
def fluent_client():
    if not _have_pyfluent():
        pytest.skip("ansys.fluent.core not importable")

    case_file = _mixing_elbow_case()
    if case_file is None:
        pytest.skip("mixing elbow case not available")

    from fastapi.testclient import TestClient
    from sim import server

    server._sessions.clear()
    yield TestClient(server.app), case_file
    try:
        TestClient(server.app).post("/disconnect", timeout=60.0)
    except Exception:
        pass
    server._sessions.clear()


def _post_exec(client, code: str, label: str) -> dict:
    response = client.post("/exec", json={"code": code, "label": label}, timeout=900.0)
    assert response.status_code == 200, response.text
    data = response.json().get("data", {})
    assert data.get("ok") is True, data.get("error")
    return data


def test_mixing_elbow_e2e_via_sim_connect(fluent_client):
    client, case_file = fluent_client

    response = client.post(
        "/connect",
        json={
            "solver": "fluent",
            "mode": "solver",
            "ui_mode": "no_gui",
            "processors": 2,
        },
        timeout=300.0,
    )
    assert response.status_code == 200, response.text
    connect_data = response.json()["data"]
    skills = connect_data.get("skills")
    assert skills is not None
    assert skills["root"] is not None
    fluent_root = Path(skills["root"])
    assert (fluent_root / "SKILL.md").is_file()

    try:
        read_code = (
            f'solver.settings.file.read_case(file_name=r"{case_file}")\n'
            f'_result = {{"step": "read-case", "ok": True}}\n'
        )
        _post_exec(client, read_code, "read-case")

        records: dict[str, dict] = {}
        for label, snippet_name in EX01_STEPS:
            snippet_path = _resolve_snippet(
                fluent_root,
                skills.get("active_sdk_layer"),
                skills.get("active_solver_layer"),
                snippet_name,
            )
            records[label] = _post_exec(
                client,
                snippet_path.read_text(encoding="utf-8"),
                label,
            )

        assert records["run-iterations"].get("result", {}).get("iterations_run") == 150
        temp_c = records["extract-temp"].get("result", {}).get("outlet_avg_temp_C")
        assert isinstance(temp_c, (int, float))
        assert 15 < temp_c < 45
    finally:
        client.post("/disconnect", timeout=60.0)


def test_direct_pyfluent_case_read_smoke():
    if not _have_pyfluent():
        pytest.skip("ansys.fluent.core not importable")
    case_file = _mixing_elbow_case()
    if case_file is None:
        pytest.skip("mixing elbow case not available")

    import ansys.fluent.core as pyfluent

    solver = pyfluent.launch_fluent(mode="solver", ui_mode="no_gui", precision="double")
    try:
        solver.settings.file.read_case(file_name=str(case_file))
        assert Path(case_file).is_file()
    finally:
        solver.exit()
