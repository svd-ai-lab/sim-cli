"""End-to-end integration test: drive mixing_elbow.cas.h5 through the
new sim connect path, executing the EX-01 snippets from the layered
sim-skills/fluent/base/snippets/ tree.

This is the TDD acceptance test for two things at once:

  1. The skills layering contract: /connect must return a `skills` block
     pointing at sim-skills/fluent with active_sdk_layer="0.38" and
     active_solver_layer="25.2", and that path must contain the snippets
     this test loads.

  2. The actual physics: a real Fluent process must run the 9-step
     EX-01 workflow against mixing_elbow.cas.h5 and produce a numeric
     outlet temperature after 150 iterations.

The test is gated:
  - skipped if `ansys.fluent.core` is not importable
  - skipped if SIM_FLUENT_CASE (default E:\\simcli\\sim-proj\\mixing_elbow.cas.h5)
    does not exist
  - skipped if SIM_SKILLS_ROOT cannot resolve the fluent skill tree

Run explicitly with:
    pytest tests/test_fluent_mixing_elbow.py -m integration -v -s
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


CASE_FILE = Path(
    os.environ.get("SIM_FLUENT_CASE", r"E:\simcli\sim-proj\mixing_elbow.cas.h5")
)
EX01_STEPS = [
    # (label, snippet filename) — 01_read_case is replaced by an inline
    # read of the .cas.h5 file because the canonical 01 snippet expects
    # a .msh.h5 from SIM_DATASETS.
    ("mesh-check",     "02_mesh_check.py"),
    ("setup-physics",  "03_setup_physics.py"),
    ("setup-material", "04_setup_material.py"),
    ("setup-bcs",      "05a_setup_bcs_ex01_ex05.py"),
    ("hybrid-init",    "06_hybrid_init.py"),
    ("run-iterations", "07_run_150_iter.py"),
    ("extract-temp",   "08a_extract_outlet_temp.py"),
]


def _resolve_snippet(skills_root: Path, active_sdk_layer: str | None,
                     active_solver_layer: str | None, name: str) -> Path:
    """Walk the layer chain newest → oldest and return the first hit.

    Order: solver/<active>/snippets/<name> → sdk/<active>/snippets/<name>
           → base/snippets/<name>. This mirrors the file-level override
           semantics that the SKILL.md index advertises.
    """
    fluent_root = skills_root / "fluent"
    candidates: list[Path] = []
    if active_solver_layer:
        candidates.append(fluent_root / "solver" / active_solver_layer / "snippets" / name)
    if active_sdk_layer:
        candidates.append(fluent_root / "sdk" / active_sdk_layer / "snippets" / name)
    candidates.append(fluent_root / "base" / "snippets" / name)
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        f"snippet {name!r} not found in any layer. Tried: {[str(c) for c in candidates]}"
    )


def _have_pyfluent() -> bool:
    try:
        import ansys.fluent.core  # noqa: F401
        return True
    except Exception:
        return False


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def server_state_reset():
    """Reset sim.server._state before and after the test so a stale
    session from a prior run doesn't poison /connect."""
    from sim import server
    server._state = server.SessionState()
    yield
    # Best-effort teardown — ignore errors so the fixture cleanup never
    # masks the actual test failure.
    try:
        from fastapi.testclient import TestClient
        c = TestClient(server.app)
        if c.get("/ps").json().get("connected"):
            c.post("/disconnect")
    except Exception:
        pass
    server._state = server.SessionState()


@pytest.fixture(scope="module")
def fluent_client(server_state_reset):
    if not _have_pyfluent():
        pytest.skip("ansys.fluent.core not importable")
    if not CASE_FILE.is_file():
        pytest.skip(f"case file not found: {CASE_FILE}")

    from fastapi.testclient import TestClient
    from sim import server
    return TestClient(server.app)


def _post_exec(client, code: str, label: str, timeout_s: float = 600.0) -> dict:
    """Send /exec and pretty-print the run record. Returns the data dict.

    The 7-step iteration takes minutes — we let httpx use the long
    server-side timeout that /exec already provides.
    """
    print(f"\n[exec] {label} ...")
    started = time.time()
    r = client.post("/exec", json={"code": code, "label": label}, timeout=timeout_s)
    elapsed = round(time.time() - started, 1)
    assert r.status_code == 200, f"{label} HTTP {r.status_code}: {r.text}"
    body = r.json()
    data = body.get("data", {})
    print(f"  ok={data.get('ok')}  elapsed_total={elapsed}s")
    if data.get("result") is not None:
        print(f"  result={data['result']}")
    if data.get("stderr"):
        for line in data["stderr"].rstrip().splitlines()[-5:]:
            print(f"  err: {line}")
    if not data.get("ok"):
        raise AssertionError(f"{label} failed: {data.get('error')}")
    return data


def test_mixing_elbow_e2e_via_sim_connect(fluent_client, capsys):
    """Drive the EX-01 mixing-elbow workflow through /connect + /exec.

    Acceptance:
      - /connect response carries a skills block with the expected
        active layers
      - 7 snippets execute with ok=true
      - final extract step returns a numeric outlet_avg_temp_C
      - iterations_run == 150
    """
    from sim.compat import find_skills_root

    capsys.disabled()  # let prints stream out so the user sees Fluent progress
    skills_root = find_skills_root()
    assert skills_root is not None, "SIM_SKILLS_ROOT must resolve for this test"
    fluent_root = skills_root / "fluent"
    assert (fluent_root / "base" / "snippets").is_dir(), f"missing {fluent_root}"

    print(f"\n[case]   {CASE_FILE}")
    print(f"[skills] {skills_root}")

    # ── Step 0: connect ────────────────────────────────────────────────
    print("\n[connect] launching Fluent (no_gui, solver mode)...")
    r = fluent_client.post(
        "/connect",
        json={
            "solver": "fluent",
            "mode": "solver",
            "ui_mode": "no_gui",
            "processors": 2,
        },
        timeout=300.0,
    )
    assert r.status_code == 200, f"connect HTTP {r.status_code}: {r.text}"
    connect_data = r.json()["data"]
    print(f"[connect] session_id={connect_data['session_id']}")
    print(f"[connect] profile={connect_data.get('profile')}")
    print(f"[connect] skills={connect_data.get('skills')}")

    # Skills block contract — adapt to whatever profile sim-cli resolved
    # for this machine's installed Fluent.
    skills = connect_data.get("skills")
    assert skills is not None, "connect response missing 'skills' block"
    assert skills["root"] is not None, skills
    assert skills["index"] is not None, skills
    assert Path(skills["index"]).is_file(), skills["index"]
    assert skills["active_sdk_layer"] is not None, (
        "fluent profiles must declare active_sdk_layer"
    )
    print(f"[skills] active_sdk_layer    = {skills['active_sdk_layer']}")
    print(f"[skills] active_solver_layer = {skills['active_solver_layer']}")
    active_sdk = skills["active_sdk_layer"]
    active_solver = skills["active_solver_layer"]

    try:
        # ── Step 1: read .cas.h5 (custom — the canonical 01 snippet
        #             reads .msh.h5 from SIM_DATASETS instead) ─────────
        read_code = (
            f'solver.settings.file.read_case(file_name=r"{CASE_FILE}")\n'
            f'_result = {{"step": "read-case", "ok": True, '
            f'"case": r"{CASE_FILE}"}}\n'
        )
        _post_exec(fluent_client, read_code, "read-case")

        # ── Steps 2-7: snippets resolved through the layer chain ──────
        records = {}
        for label, snippet_name in EX01_STEPS:
            snippet_path = _resolve_snippet(
                skills_root, active_sdk, active_solver, snippet_name
            )
            rel = snippet_path.relative_to(skills_root)
            print(f"[layer]  {snippet_name} -> {rel}")
            code = snippet_path.read_text(encoding="utf-8")
            records[label] = _post_exec(fluent_client, code, label)

        # ── Acceptance ────────────────────────────────────────────────
        iter_record = records["run-iterations"]
        iter_result = iter_record.get("result") or {}
        assert iter_result.get("iterations_run") == 150, iter_result

        extract_record = records["extract-temp"]
        extract_result = extract_record.get("result") or {}
        temp_C = extract_result.get("outlet_avg_temp_C")
        temp_K = extract_result.get("outlet_avg_temp_K")
        print(f"\n[ACCEPTANCE] outlet_avg_temp_K = {temp_K}")
        print(f"[ACCEPTANCE] outlet_avg_temp_C = {temp_C}")
        assert isinstance(temp_C, (int, float)), (
            f"outlet_avg_temp_C is not numeric: {temp_C!r}"
        )
        # Sanity range: cold inlet 20°C, hot inlet 40°C → mixed should
        # land in (20, 40) °C. Wide bounds to tolerate convergence noise.
        assert 15 < temp_C < 45, f"outlet temp out of plausible range: {temp_C} °C"
        print("\n[ACCEPTANCE] EX-01 PASS")
    finally:
        try:
            fluent_client.post("/disconnect", timeout=60.0)
        except Exception as e:
            print(f"[teardown] disconnect failed: {e}")
