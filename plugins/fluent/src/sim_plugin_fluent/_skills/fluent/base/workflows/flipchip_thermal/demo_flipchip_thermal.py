"""
Flip-chip BGA thermal characterization using Ansys Fluent.

Computes JEDEC-style thermal resistances (Theta-JB, Theta-JC) for a
flip-chip package on a 2S2P PCB using conduction-only analysis.

Method follows the Ozen Engineering walkthrough video by Luis Maldonado:
  https://www.youtube.com/watch?v=xMp4CG80Wq8
And the companion blog post:
  https://blog.ozeninc.com/resources/flip-chip-thermal-characterization-using-ansys-fluent

Case file: Flip_chip_demo_simplified.cas.h5 (from the Ozen blog).
  The case ships bare: materials + geometry + mesh only. Energy equation is off,
  there are no named expressions, and no source terms are enabled on any solid
  zone. Every piece of the thermal physics setup (energy, heat source, BCs) is
  built by THIS SCRIPT.

Note on reference values: the Ozen blog publishes theta_JB = 0.681 K/W and
theta_JC = 1.447 K/W, but those numbers are inconsistent with the temperatures
the same blog lists at the video's 5 W power (ΔT/5W gives ~4.05 and ~5.70 K/W).
We regress against the temperature-derived values. See README.md.

Known pyfluent quirk: on this case `solver.fields.reduction.maximum(...)`
fails with 'api-checks-before-command-or-query ... temp_expr_1/get-value'.
Use `solver.settings.solution.report_definitions.surface[...]` + compute()
instead — done throughout this script.

Tested with: ansys-fluent-core 0.38.1, Fluent 2025 R2 (v252)

This is a reference script — NOT meant for sim exec (it calls launch_fluent).
The sim-native version uses sim connect + sim exec steps; see README.md.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SEP = "-" * 60
TESTED_PYFLUENT = "0.38"

_datasets = os.environ.get("SIM_DATASETS")
if not _datasets:
    raise RuntimeError(
        "SIM_DATASETS env var not set. Either run `uv run fetch_case.py` "
        "(from this workflow dir) and export SIM_DATASETS as it instructs, "
        "or set it manually to the directory containing "
        "flipchip/Flip_chip_demo_simplified.cas.h5."
    )
CASE_FILE = Path(_datasets) / "flipchip" / "Flip_chip_demo_simplified.cas.h5"
if not CASE_FILE.exists():
    raise RuntimeError(
        f"Case file not found: {CASE_FILE}\n"
        f"Run `uv run fetch_case.py` from {Path(__file__).parent} to download it."
    )

# Matches the Ozen walkthrough video
DIE_POWER_W = 5.0              # named expression "power" in the video
T_AMBIENT_K = 298.15           # 25 degC
H_NAT_CONV_W_M2K = 10.0        # natural convection on package exterior, Theta-JB only
#                                (Luis: "a heat transfer coefficient of 10, that is
#                                 common in natural convection")

# Wall groupings (verified against the simplified case and the video transcript)
# Die silicon side-faces + other flip-chip interior walls — always adiabatic
DIE_ADIABATIC_WALLS = [
    "die_sides",
    "thermal_paste_sides",
    "substrate_sides",
    "underfilldie_sides", "underfillpcb_sides",
]

# PCB bottom + sides + top external surfaces exposed to ambient. In Theta-JB
# these see natural convection; in Theta-JC they get clamped to 298.15 K.
# Luis: "for the bottoms and the boundaries that are outside the ring, we're
# going to set a convective boundary condition ... same boundary condition
# is going to be replicated in the sides and in the top."
PACKAGE_CONV_WALLS = [
    "thermal_paste_top",
    "substrate_top",
    "pcb_top",
    "pcb_sides", "pcb_sides.1", "pcb_sides.2", "pcb_sides.3",
    "pcb_sides.4", "pcb_sides.5", "pcb_sides.6",
    "pcb_bottom",
]

# Theta-JB sinks: fixed T on the PCB rings (both top and bottom rings).
# Luis: "fixed temperature that is going to be placed in the rings ...
# copy this also to the top" (i.e. both the bottom rings and the top rings
# get fixed T = 25 C).
PCB_RING_WALLS = [
    "pcb_bottom_ring", "pcb_bottom_inside_ring",
    "pcb_top_ring", "pcb_top_inside_ring",
]


def step(n: int, title: str) -> None:
    print(f"\n[Step {n}] {title}")
    print(SEP)


def set_adiabatic(solver, wall_name: str) -> bool:
    try:
        w = solver.settings.setup.boundary_conditions.wall[wall_name]
        w.thermal.thermal_condition = "Heat Flux"
        w.thermal.heat_flux.value = 0.0
        return True
    except Exception:
        return False


def set_fixed_temperature(solver, wall_name: str, T: float) -> bool:
    try:
        w = solver.settings.setup.boundary_conditions.wall[wall_name]
        w.thermal.thermal_condition = "Temperature"
        w.thermal.temperature.value = T
        return True
    except Exception:
        return False


def set_convection(solver, wall_name: str, h: float, T_inf: float) -> bool:
    try:
        w = solver.settings.setup.boundary_conditions.wall[wall_name]
        w.thermal.thermal_condition = "Convection"
        w.thermal.heat_transfer_coeff.value = h
        w.thermal.free_stream_temp.value = T_inf
        return True
    except Exception:
        return False


def _parse_compute(out) -> dict:
    """report_definitions.compute() returns [{'name': [value, 'unit']}, ...]"""
    vals: dict = {}
    if isinstance(out, list):
        for entry in out:
            if isinstance(entry, dict):
                for k, v in entry.items():
                    try:
                        vals[k] = float(v[0])
                    except Exception:
                        vals[k] = v
    return vals


# -- Step 1: import ------------------------------------------------
step(1, "Import ansys-fluent-core")

try:
    import ansys.fluent.core as pyfluent
    pyfluent_version = pyfluent.__version__
    print(f"  pyfluent version = {pyfluent_version}")
    major_minor = ".".join(pyfluent_version.split(".")[:2])
    if major_minor != TESTED_PYFLUENT:
        print(f"  WARNING: this script was tested with pyfluent {TESTED_PYFLUENT}, "
              f"running {major_minor} — API differences possible")
except ImportError as e:
    print(f"  ERROR: import failed - {e}")
    sys.exit(1)

import ansys.fluent.core.fluent_connection as _fc
_fc._is_localhost = lambda address: True

# -- Step 2: locate case file --------------------------------------
step(2, "Locate flip-chip case file")

if not CASE_FILE.exists():
    print(f"  ERROR: case file not found: {CASE_FILE}")
    print("  Download from: https://blog.ozeninc.com/hubfs/Flip_chip_demo_simplified.zip")
    sys.exit(1)
print(f"  found: {CASE_FILE.name}")

# -- Step 3: launch Fluent solver session --------------------------
step(3, "Launch Fluent solver session (GUI)")

try:
    solver = pyfluent.launch_fluent(
        mode="solver",
        ui_mode="gui",
        precision="double",
        processor_count=4,
    )
    print(f"  session type = {type(solver).__name__}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    sys.exit(1)

# -- Step 4: read case ---------------------------------------------
step(4, "Read case file")

try:
    solver.settings.file.read_case(file_name=str(CASE_FILE))
    print(f"  Case loaded: {CASE_FILE.name}")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    solver.exit()
    sys.exit(1)

# -- Step 5: mesh check --------------------------------------------
step(5, "Mesh check")
try:
    solver.settings.mesh.check()
    print("  Mesh check OK")
except Exception as e:
    print(f"  WARNING: {type(e).__name__}: {e}")

# -- Step 6: enable energy + laminar -------------------------------
step(6, "Enable energy equation (laminar — no fluid zones)")
try:
    solver.settings.setup.models.energy = {"enabled": True}
    try:
        solver.settings.setup.models.viscous = {"model": "laminar"}
    except Exception:
        pass  # some pyfluent builds reject the assignment on solid-only cases
    print("  Energy enabled")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    solver.exit()
    sys.exit(1)

# -- Step 7: set die heat source -----------------------------------
step(7, f"Set volumetric heat source on die ({DIE_POWER_W} W via named expression 'power')")
try:
    ne = solver.settings.setup.named_expressions
    ne["power"] = {"definition": f"{DIE_POWER_W} [W]"}

    die = solver.settings.setup.cell_zone_conditions.solid["flipchip-die-die"]
    die.sources.enable = True
    die.sources.terms = {
        "energy": [{"option": "value", "value": "power/Volume(['flipchip-die-die'])"}]
    }
    print(f"  power = {DIE_POWER_W} W, source = power/Volume(['flipchip-die-die'])")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    solver.exit()
    sys.exit(1)

# -- Step 8: create die_surface from die cell zone -----------------
step(8, "Create die_surface from the die cell zone (for report extraction)")
try:
    solver.tui.surface.zone_surface("die_surface", "flipchip-die-die")
    print("  die_surface created")
except Exception as e:
    print(f"  WARNING: {type(e).__name__}: {e}")

# -- Step 9: Theta-JB BCs ------------------------------------------
step(9, "Set BCs for Theta-JB "
        "(die_sides adiabatic, package natural convection, PCB bottom rings fixed T)")

n_adi = sum(set_adiabatic(solver, w) for w in DIE_ADIABATIC_WALLS)
n_conv = sum(set_convection(solver, w, H_NAT_CONV_W_M2K, T_AMBIENT_K) for w in PACKAGE_CONV_WALLS)
n_fix = sum(set_fixed_temperature(solver, w, T_AMBIENT_K) for w in PCB_RING_WALLS)
print(f"  adiabatic: {n_adi}/{len(DIE_ADIABATIC_WALLS)}")
print(f"  convection (h={H_NAT_CONV_W_M2K}, T_inf={T_AMBIENT_K}): "
      f"{n_conv}/{len(PACKAGE_CONV_WALLS)}")
print(f"  fixed T={T_AMBIENT_K}: {n_fix}/{len(PCB_RING_WALLS)}")

# -- Step 10: initialize and solve Theta-JB ------------------------
step(10, "Initialize and solve (Theta-JB)")
solver.settings.solution.initialization.hybrid_initialize()
solver.settings.solution.run_calculation.iterate(iter_count=200)
print("  Solver finished")

# -- Step 11: extract Theta-JB -------------------------------------
step(11, "Extract Theta-JB results")
theta_jb = t_die_max_jb = t_board_jb = None
try:
    rd = solver.settings.solution.report_definitions
    rd.surface["die_t_max"] = {
        "report_type": "surface-facetmax",
        "field": "temperature",
        "surface_names": ["die_surface"],
    }
    # "BGA–PCB connection temperature" — closest proxy in the simplified mesh
    # is the inside ring of pcb_top (the annulus directly under the package footprint).
    rd.surface["board_t_avg"] = {
        "report_type": "surface-areaavg",
        "field": "temperature",
        "surface_names": ["pcb_top_inside_ring"],
    }
    vals = _parse_compute(rd.compute(report_defs=["die_t_max", "board_t_avg"]))
    t_die_max_jb = vals.get("die_t_max")
    t_board_jb = vals.get("board_t_avg")
    if t_die_max_jb is not None and t_board_jb is not None:
        theta_jb = (t_die_max_jb - t_board_jb) / DIE_POWER_W
        print(f"  T_die_max   = {t_die_max_jb:.4f} K ({t_die_max_jb - 273.15:.2f} degC)")
        print(f"  T_board_avg = {t_board_jb:.4f} K  (pcb_top_inside_ring)")
        print(f"  Theta-JB    = {theta_jb:.4f} K/W at P = {DIE_POWER_W} W")
except Exception as e:
    print(f"  WARNING: extraction failed - {type(e).__name__}: {e}")

# -- Step 12: Theta-JC BCs -----------------------------------------
step(12, "Set BCs for Theta-JC (fixed T=298.15 K on ALL outer walls — Luis's shortcut)")
all_walls = DIE_ADIABATIC_WALLS + PACKAGE_CONV_WALLS + PCB_RING_WALLS
n_fix_jc = sum(set_fixed_temperature(solver, w, T_AMBIENT_K) for w in all_walls)
print(f"  Fixed T={T_AMBIENT_K}: {n_fix_jc}/{len(all_walls)}")

# -- Step 13: re-initialize and solve Theta-JC ---------------------
step(13, "Re-initialize and solve (Theta-JC)")
solver.settings.solution.initialization.hybrid_initialize()
solver.settings.solution.run_calculation.iterate(iter_count=200)
print("  Solver finished")

# -- Step 14: extract Theta-JC -------------------------------------
step(14, "Extract Theta-JC results")
theta_jc = t_die_max_jc = t_case_jc = None
try:
    rd = solver.settings.solution.report_definitions
    rd.surface["case_t_avg"] = {
        "report_type": "surface-areaavg",
        "field": "temperature",
        "surface_names": ["thermal_paste_top"],
    }
    vals = _parse_compute(rd.compute(report_defs=["die_t_max", "case_t_avg"]))
    t_die_max_jc = vals.get("die_t_max")
    t_case_jc = vals.get("case_t_avg")
    if t_die_max_jc is not None and t_case_jc is not None:
        theta_jc = (t_die_max_jc - t_case_jc) / DIE_POWER_W
        print(f"  T_die_max = {t_die_max_jc:.4f} K ({t_die_max_jc - 273.15:.2f} degC)")
        print(f"  T_case    = {t_case_jc:.4f} K  (thermal_paste_top)")
        print(f"  Theta-JC  = {theta_jc:.4f} K/W at P = {DIE_POWER_W} W")
except Exception as e:
    print(f"  WARNING: extraction failed - {type(e).__name__}: {e}")

# -- Done ----------------------------------------------------------
print(f"\n{'='*60}")
print("Flip-chip thermal characterization complete")
print(f"{'='*60}")

results = {
    "status": "ok",
    "workflow": "flipchip-thermal-characterization",
    "method_source": "https://www.youtube.com/watch?v=xMp4CG80Wq8",
    "case_file": str(CASE_FILE),
    "die_power_w": DIE_POWER_W,
    "t_ambient_k": T_AMBIENT_K,
    "h_nat_conv_w_m2k": H_NAT_CONV_W_M2K,
    "theta_jb": {
        "value_k_per_w": theta_jb,
        "t_die_max_k": t_die_max_jb,
        "t_board_k": t_board_jb,
    },
    "theta_jc": {
        "value_k_per_w": theta_jc,
        "t_die_max_k": t_die_max_jc,
        "t_case_k": t_case_jc,
    },
}
print(json.dumps(results, indent=2, default=str))

try:
    solver.exit()
    print("  Fluent session closed")
except Exception:
    pass
