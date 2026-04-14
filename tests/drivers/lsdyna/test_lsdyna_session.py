"""Session-mode E2E tests for LS-DYNA driver.

Exercises the launch -> exec (build deck) -> inspect -> exec (solve)
-> inspect (DPF results) -> disconnect lifecycle through the driver
methods directly. This is the same path that `sim connect/exec/inspect`
takes via the HTTP server (which is driver-agnostic).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.drivers.lsdyna import LsDynaDriver

# Skip if PyDyna or LS-DYNA not available
try:
    import ansys.dyna.core  # noqa: F401
    HAS_PYDYNA = True
except ImportError:
    HAS_PYDYNA = False

driver = LsDynaDriver()
HAS_LSDYNA = bool(driver.detect_installed())

pytestmark = pytest.mark.skipif(
    not (HAS_PYDYNA and HAS_LSDYNA),
    reason="Requires ansys-dyna-core + LS-DYNA installation",
)


# ---------------------------------------------------------------------------
# Lifecycle smoke
# ---------------------------------------------------------------------------


class TestLaunchDisconnect:
    def test_supports_session(self):
        d = LsDynaDriver()
        assert d.supports_session is True

    def test_launch_returns_session_id(self, tmp_path):
        d = LsDynaDriver()
        info = d.launch(workdir=str(tmp_path))
        try:
            assert info["ok"] is True
            assert "session_id" in info
            assert info["pydyna_available"] is True
            assert info["workdir"] == str(tmp_path)
        finally:
            d.disconnect()

    def test_disconnect_idempotent(self):
        d = LsDynaDriver()
        # disconnect without launch should be a no-op
        r1 = d.disconnect()
        assert r1["ok"] is True
        # launch then disconnect twice
        d.launch()
        d.disconnect()
        r2 = d.disconnect()
        assert r2["ok"] is True


# ---------------------------------------------------------------------------
# Build deck via exec
# ---------------------------------------------------------------------------


class TestDeckBuild:
    @pytest.fixture
    def session(self, tmp_path):
        d = LsDynaDriver()
        d.launch(workdir=str(tmp_path))
        yield d
        d.disconnect()

    def test_empty_deck_summary(self, session):
        info = session.query("deck.summary")
        assert info["ok"] is True
        assert info["n_keywords"] == 0
        assert info["has_termination"] is False

    def test_add_control_termination(self, session):
        r = session.run("deck.append(kwd.ControlTermination(endtim=1.0))", "ctrl")
        assert r["ok"] is True, r.get("error")
        info = session.query("deck.summary")
        assert info["n_keywords"] == 1
        assert info["has_termination"] is True
        assert "ControlTermination" in info["keyword_types"]

    def test_add_material_via_class(self, session):
        r = session.run(
            "deck.append(kwd.MatElastic(mid=1, ro=7.85e-6, e=210.0, pr=0.3))",
            "mat",
        )
        assert r["ok"] is True
        info = session.query("deck.summary")
        assert info["has_material"] is True

    def test_set_title(self, session):
        session.run("deck.title = 'session-built model'", "title")
        info = session.query("deck.summary")
        assert info["title"] == "session-built model"

    def test_invalid_code_returns_error(self, session):
        r = session.run("not_a_real_function()", "bad")
        assert r["ok"] is False
        assert "NameError" in r["error"]

    def test_result_assignment(self, session):
        r = session.run("_result = {'pi': 3.14, 'count': 42}", "ret")
        assert r["ok"] is True
        assert r["result"] == {"pi": 3.14, "count": 42}

    def test_deck_text_query(self, session):
        session.run("deck.append(kwd.ControlTermination(endtim=0.001))", "ctrl")
        info = session.query("deck.text")
        assert info["ok"] is True
        assert "*CONTROL_TERMINATION" in info["text"]
        assert "*KEYWORD" in info["text"]


# ---------------------------------------------------------------------------
# End-to-end: build → solve → DPF post-process via session
# ---------------------------------------------------------------------------


class TestSessionEndToEnd:
    @pytest.fixture(scope="class")
    def solved_session(self, tmp_path_factory):
        wd = tmp_path_factory.mktemp("lsdyna_session_e2e")
        d = LsDynaDriver()
        d.launch(workdir=str(wd))

        # Build a complete single-hex tension model entirely via session exec
        build_code = """
import pandas as pd

deck.title = "Single hex element tension test (session-built)"

# Control
deck.append(kwd.ControlTermination(endtim=1.0))

# Material (steel)
deck.append(kwd.MatElastic(mid=1, ro=7.85e-6, e=210.0, pr=0.3))

# Section
deck.append(kwd.SectionSolid(secid=1, elform=1))

# Part
deck.append(kwd.Part(pid=1, mid=1, secid=1))

# Nodes — 1mm cube
node = kwd.Node()
node.nodes = pd.DataFrame({
    "nid": [1, 2, 3, 4, 5, 6, 7, 8],
    "x":   [0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0, 0.0],
    "y":   [0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 1.0],
    "z":   [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0],
})
deck.append(node)

# Element
elem = kwd.ElementSolid()
elem.elements = pd.DataFrame({
    "eid": [1], "pid": [1],
    "n1": [1], "n2": [2], "n3": [3], "n4": [4],
    "n5": [5], "n6": [6], "n7": [7], "n8": [8],
})
deck.append(elem)

# Boundary: fix bottom face
bc = kwd.BoundarySpcNode()
bc.nodes = pd.DataFrame({
    "nid":   [1, 2, 3, 4],
    "cid":   [0, 0, 0, 0],
    "dofx":  [1, 1, 1, 1],
    "dofy":  [1, 1, 1, 1],
    "dofz":  [1, 1, 1, 1],
    "dofrx": [0, 0, 0, 0],
    "dofry": [0, 0, 0, 0],
    "dofrz": [0, 0, 0, 0],
})
deck.append(bc)

# Load curve and load
curve = kwd.DefineCurve(lcid=1)
curve.curves = pd.DataFrame({"a1": [0.0, 0.1, 1.0], "o1": [0.0, 1.0, 1.0]})
deck.append(curve)

load = kwd.LoadNodePoint()
load.nodes = pd.DataFrame({
    "nid":  [5, 6, 7, 8],
    "dof":  [3, 3, 3, 3],
    "lcid": [1, 1, 1, 1],
    "sf":   [0.0025, 0.0025, 0.0025, 0.0025],
})
deck.append(load)

# Output
deck.append(kwd.DatabaseGlstat(dt=0.01))
deck.append(kwd.DatabaseBinaryD3Plot(dt=0.1))
"""
        r = d.run(build_code, "build")
        assert r["ok"] is True, r.get("error")

        # Write the deck
        write = d.run("deck.export_file(str(workdir / 'session.k'))", "write")
        assert write["ok"] is True, write.get("error")

        # Solve
        solve = d.run(
            "run_dyna('session.k', working_directory=str(workdir))",
            "solve",
        )
        # run_dyna may print to stdout but should not error
        assert solve["ok"] is True, solve.get("error")

        yield d
        d.disconnect()

    def test_deck_built_via_session(self, solved_session):
        info = solved_session.query("deck.summary")
        assert info["ok"] is True
        assert info["n_keywords"] >= 10
        assert info["has_termination"] is True
        assert info["has_material"] is True
        assert info["has_nodes"] is True
        assert info["has_elements"] is True

    def test_d3plot_produced(self, solved_session):
        info = solved_session.query("workdir.files")
        assert info["ok"] is True
        assert info["d3plot_present"] is True
        assert "session.k" in info["files"]
        assert "d3hsp" in info["files"]

    def test_dpf_model_auto_loaded(self, solved_session):
        # DPF model should auto-load after run_dyna populates d3plot
        info = solved_session.query("session.summary")
        assert info["model_loaded"] is True

    def test_results_summary(self, solved_session):
        info = solved_session.query("results.summary")
        assert info["ok"] is True, info.get("error")
        assert info["n_states"] >= 10  # ~12 from dt=0.1, endtim=1.0
        assert info["n_nodes"] == 8
        assert info["n_elements"] == 1

    def test_extract_displacement_via_exec(self, solved_session):
        code = """
import numpy as np
disp_op = model.results.displacement.on_last_time_freq()
disp_field = disp_op.eval().get_field(0)
disp_arr = np.asarray(disp_field.data).reshape(-1, 3)
_result = {
    'max_disp_mm': float(np.linalg.norm(disp_arr, axis=1).max()),
    'n_nodes': int(disp_arr.shape[0]),
}
"""
        r = solved_session.run(code, "post-disp")
        assert r["ok"] is True, r.get("error")
        assert r["result"]["n_nodes"] == 8
        # Elastic regime, small disp expected
        assert 0 < r["result"]["max_disp_mm"] < 0.1

    def test_extract_kinetic_energy(self, solved_session):
        code = """
gke_op = dpf.operators.result.global_kinetic_energy()
gke_op.inputs.data_sources.connect(_data_sources)
ke = gke_op.eval().get_field(0).data
_result = {
    'n_states': len(ke),
    'ke_max': float(max(ke)),
    'ke_final': float(ke[-1]),
}
"""
        r = solved_session.run(code, "post-ke")
        assert r["ok"] is True, r.get("error")
        # Quasi-static load → KE essentially zero
        assert abs(r["result"]["ke_final"]) < 1e-10


# ---------------------------------------------------------------------------
# Last-result tracking
# ---------------------------------------------------------------------------


class TestLastResult:
    def test_last_result_after_runs(self, tmp_path):
        d = LsDynaDriver()
        d.launch(workdir=str(tmp_path))
        try:
            d.run("_result = 1", "first")
            d.run("_result = 2", "second")
            last = d.query("last.result")
            assert last["ok"] is True
            assert last["result"] == 2
            assert last["label"] == "second"
        finally:
            d.disconnect()
