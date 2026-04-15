# Changelog

All notable changes to `sim-cli` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per-commit history lives in `git log`; this file is a curated list of user-visible
changes at milestone boundaries.

## [Unreleased]

### Added

- **Pure-Python simulation ecosystem — 13 new pip-installable drivers.** All installed via `pip install <pkg>` on Python 3.7+, executed one-shot via `sim run script.py --solver <name>`, each verified against an analytical / textbook benchmark:
  - `openseespy` 3.5 (structural / earthquake FEM) — cantilever-beam tip deflection, rel err 1.3e-12
  - `sfepy` 2025.4 (pure-Python FEM) — Poisson on unit square, 1.3% err on 8×8 mesh
  - `cantera` 2.6 (combustion / chemical kinetics) — CH4/air adiabatic flame T = 2225.5 K (textbook 2225 K)
  - `openmdao` 3.30 (NASA MDAO framework) — Sellar coupled MDA y1=25.59, y2=12.06
  - `fipy` 4.0 (NIST finite-volume PDE) — 1D steady Poisson, err 1.6e-15
  - `pymoo` 0.6 (multi-objective optimization) — NSGA-II ZDT1, 36 Pareto solutions
  - `pyomo` 6.6 (optimization modeling) — classic LP via HiGHS backend, (2,6) obj=36
  - `simpy` 4.0 (discrete-event simulation) — M/M/1 queue, L err 1.9 % vs theory
  - `trimesh` 4.4 (triangular mesh processing) — box V=24 exact, sphere 0.2 % err
  - `devito` 4.8 (symbolic FD + JIT C codegen) — 2D heat diffusion, mass conservation 4e-7
  - `coolprop` 6.4 (REFPROP-equivalent thermo-properties) — water @ 1 atm T_sat = 373.124 K
  - `scikit_rf` 1.1 (RF / microwave network analysis) — 50 Ω short/open/match S11 = −1/+1/0 to machine precision
  - `pandapower` 2.11 (Fraunhofer IEE power-system analysis) — 2-bus PF, vm_pu = 0.998, losses 1.4 kW
- **Open-source Linux CAE — 9 new drivers** reachable via remote `sim serve` on Linux. Each with Tier-1 unit tests + Tier-4 real-E2E physics verification:
  - `calculix` (CCX, Abaqus-dialect `.inp`) — cantilever tip U2 = −2002 (0.1 % err vs analytical 2000)
  - `gmsh` (`.geo` DSL / Python API mesh generator) — 258 nodes, 1278 cells on unit sphere
  - `su2` (open-source multi-physics CFD) — NACA0012 inviscid, RMS[Rho] dropped 3.5 orders
  - `lammps` (classical molecular dynamics) — LJ NVT, final T = 1.07 (target 1.5)
  - `scikit_fem` (pure-Python FEM) — Poisson on unit square, u_max = 0.07345 (0.3 % err)
  - `elmer` (`.sif` multi-physics FEM) — steady heat, max_temp = 0.07426 (0.8 % err)
  - `meshio` (20+ mesh format converter) — round-trip preserves 258 nodes
  - `pyvista` (VTK post-processing) — sphere area 0.76 % err, volume 1.37 % err (headless PNG)
  - `pymfem` 4.8 (Python bindings for LLNL's MFEM C++ FEM) — Poisson u_max = 0.07353 (0.2 % err via UMFPackSolver)
- **MAPDL driver (Phase 1 + Phase 2).** New Ansys MAPDL driver covering both one-shot and persistent-session modes. Phase 1: subprocess execution of PyMAPDL scripts via `sim run script.py --solver mapdl`, with detect / lint / run_file / parse_output and 4-profile compatibility matrix (24.1–25.2). Phase 2: live `Mapdl` gRPC client held across `sim exec` calls; snippet namespace exposes `mapdl`, `np`, `launch_mapdl`, `workdir`, `_result`; query targets `session.summary` / `mesh.summary` / `workdir.files` / `results.summary` / `last.result` flow through the cross-driver inspect fallback. 16 tests (15 unit + 1 session integration). Phase 1 E2E: 2D I-beam (BEAM188, max UZ −0.0265 cm) + 3D notched plate (SOLID186, K_t=1.98 vs Roark 1.60). Phase 2 E2E: same 2D beam re-driven through 10-step session (4 exec + 4 inspect + connect / disconnect) — identical physics, full transcript saved. Headless PyVista contour PNGs throughout (no GUI scripting needed).
