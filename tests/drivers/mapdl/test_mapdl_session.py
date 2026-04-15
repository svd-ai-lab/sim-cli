"""MAPDL Phase 2 session-mode integration test.

Actually launches MAPDL via PyMAPDL and drives it through the
driver's launch/run/query/disconnect protocol. Slow (≥10 s) — marked
integration so it doesn't run by default.
"""
from __future__ import annotations

import pytest

from sim.drivers.mapdl import MapdlDriver

# Skip if pymapdl is not available
try:
    import ansys.mapdl.core  # noqa: F401
    HAS_PYMAPDL = True
except ImportError:
    HAS_PYMAPDL = False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_PYMAPDL, reason="pymapdl not installed"),
]


class TestMapdlSession:
    """Full lifecycle: launch → exec → query → exec (solve) → disconnect."""

    def test_full_lifecycle(self):
        driver = MapdlDriver()
        assert driver.supports_session is True

        # ---- launch ------------------------------------------------------
        info = driver.launch()
        try:
            assert info["ok"] is True
            assert info["session_id"].startswith("mapdl-")
            assert info["mapdl_version"]  # non-empty

            # ---- exec: build a trivial 2-element BEAM188 model -----------
            build_code = """
mapdl.prep7()
mapdl.et(1, "BEAM188")
mapdl.mp("EX", 1, 2.0e11)
mapdl.mp("PRXY", 1, 0.3)
mapdl.sectype(1, "BEAM", "RECT")
mapdl.secoffset("CENT")
mapdl.secdata(0.01, 0.01)
mapdl.n(1, 0, 0, 0); mapdl.n(2, 1, 0, 0); mapdl.n(3, 2, 0, 0)
mapdl.e(1, 2); mapdl.e(2, 3)
mapdl.finish()
_result = {"nodes": int(len(mapdl.mesh.nnum)),
           "elems": int(len(mapdl.mesh.enum))}
""".strip()
            build = driver.run(build_code, label="build")
            assert build["ok"] is True, build.get("error")
            assert build["result"] == {"nodes": 3, "elems": 2}

            # ---- query: mesh.summary -------------------------------------
            mesh = driver.query("mesh.summary")
            assert mesh["ok"] is True
            assert mesh["n_nodes"] == 3
            assert mesh["n_elements"] == 2

            # ---- query: session.summary ----------------------------------
            sess = driver.query("session.summary")
            assert sess["ok"] is True
            assert sess["n_runs"] == 1
            assert sess["alive"] is True

            # ---- exec: solve ---------------------------------------------
            solve_code = """
mapdl.slashsolu()
for c in ("UX","UY","UZ","ROTX","ROTY","ROTZ"):
    mapdl.d(1, c)
mapdl.f(3, "FY", -100.0)
mapdl.antype("STATIC"); mapdl.solve(); mapdl.finish()
mapdl.post1(); mapdl.set(1, 1)
uy = mapdl.post_processing.nodal_displacement("Y")
_result = {"min_uy": float(uy.min()), "n_nodes": int(len(uy))}
""".strip()
            solve = driver.run(solve_code, label="solve")
            assert solve["ok"] is True, solve.get("error")
            assert solve["result"]["min_uy"] < 0.0      # tip deflects down

            # ---- query: workdir.files ------------------------------------
            files = driver.query("workdir.files")
            assert files["ok"] is True
            assert files["has_rst"] is True             # .rst written by solve

            # ---- query: unknown target -----------------------------------
            unknown = driver.query("no.such.target")
            assert unknown["ok"] is False
            assert "Unknown query" in unknown["error"]

        finally:
            # ---- disconnect ----------------------------------------------
            out = driver.disconnect()
            assert out["ok"] is True
            assert out["disconnected"] is True

        # Calling disconnect again is idempotent
        again = driver.disconnect()
        assert again["ok"] is True
