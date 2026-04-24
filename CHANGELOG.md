# Changelog

All notable changes to `sim-cli` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Per-commit history lives in `git log`; this file is a curated list of user-visible
changes at milestone boundaries.

## [Unreleased]

### Added

- **Probe observability — 41/41 driver coverage + fact-only contract.** Every driver in the registry now attaches structured `diagnostics` + `artifacts` lists to every `run()` result. Coverage:
  - **10 session drivers** (`fluent`, `comsol`, `flotherm`, `workbench`, `mechanical`, `mapdl`, `ls_dyna`, `ansa`, `matlab`, `cfx`) — each `__init__` sets `self.probes = _default_<solver>_probes()`; the execute-path is split into `_dispatch(code, label)` (raw subprocess behaviour, returns a dict) wrapped by `run(code, label)` (builds an `InspectCtx`, calls `collect_diagnostics(self.probes, ctx)`, attaches outputs).
  - **31 one-shot drivers** (pybamm, openfoam, abaqus, starccm, icem, isaac, newton, calculix, gmsh, su2, lammps, scikit_fem, elmer, meshio, pyvista, pymfem, openseespy, sfepy, cantera, openmdao, fipy, pymoo, pyomo, simpy, trimesh, devito, coolprop, scikit_rf, pandapower, paraview, hypermesh) — covered uniformly via `runner.execute_script`, which calls `_attach_probes(result, solver)` → `generic_probes()` against the completed `RunResult`.
  - **Active probes (fact-only):** `ProcessMetaProbe` (exit code + wall time), `RuntimeTimeoutProbe` (hung-snippet detection), `StdoutJsonTailProbe` (last JSON line on stdout / `_result` fallback), `PythonTracebackProbe` (structured traceback parsing), `WorkdirDiffProbe` (new files → Artifacts), plus optional `GuiDialogProbe` / `ScreenshotProbe` in GUI mode and `SdkAttributeProbe` reading raw SDK values where applicable.

- **`sim.gui` subpackage — cross-driver GUI actuation (Phase 3 P0).** New actuation layer that every GUI-capable driver now injects into its `sim exec` namespace, separate from (and complementary to) the Phase 1-2 observation layer:
  - `sim/gui/_win32_dialog.py` — Win32 ctypes primitives (`enum_visible_windows`, `find_dialog_by_title`, `fill_file_dialog`, `close_window`, `dismiss_windows_by_title_fragment`), extracted from the flotherm driver so every driver can share them.
  - `sim/gui/_pywinauto_tools.py` — subprocess-isolated pywinauto UIA helpers (`find_window` / `click_by_name` / `send_text` / `close_window` / `activate_window` / `screenshot_window` / `snapshot_uia_tree` / `list_windows`). Each call runs in a fresh `python -c` subprocess to keep the main process's COM apartment clean (pywinauto has a history of COM pollution on repeated calls).
  - `sim/gui/__init__.py` — `GuiController` + `SimWindow` facade. Agent-visible API: `gui.find(title_contains=...)`, `dlg.click("OK")`, `dlg.send_text("C:\\path", into="File name")`, `dlg.screenshot()`, `gui.list_windows()`, `gui.snapshot(max_depth=5)`. On non-Windows / headless: methods return `{"ok": False, "error": ...}` without raising.
  - Fluent + COMSOL drivers construct `self._gui = GuiController(<process filter>)` during `launch()` when `ui_mode=gui|desktop`, and pass `extra_namespace={"gui": self._gui}` through `run()`. Flotherm's `_win32_backend.py` migrated to import from `sim.gui._win32_dialog` — behaviour unchanged, code no longer duplicated.
  - `POST /connect` advertises availability: `data.tools = ["gui"]` + `data.tool_refs = {"gui": "sim-skills/sim-cli/gui/SKILL.md"}`, emitted only when the active driver constructed a `GuiController` at launch. Lets agents self-discover without forcing them to re-read the skill tree.
  - 13 L1 unit tests (monkey-patched pywinauto, including `/connect` contract test) + two real-solver L3 e2e scripts:
    - `tests/inspect/e2e_flotherm_mobile_demo.py` — imports the bundled `Mobile_Demo-Steady_State.pack`, triggers solve, polls the Message Window dock. Converges (I/8003) in clock time 8 s, 153,449 grid cells, zero errors / warnings.
    - `tests/inspect/e2e_comsol_surface_mount.py` + `_extract_comsol_Tmax.py` — runs the full 6-step `surface_mount_package` sim-skills workflow (geometry → materials → physics → mesh → solve → plot), then reads the saved `.mph` via mph to report `Tmax = 97.32 °C` over 49,356 solution nodes (stationary solve 10.9 s, 8468 tetrahedral elements, min quality 0.154).
  - Companion docs live in sibling sim-skills repo at `sim-skills/sim-cli/gui/SKILL.md` (full API reference + 3 snippets) with matching "GUI actuation" sections added to the `fluent`, `comsol`, `flotherm` SKILL files.

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

### Changed

- **Removed every solver-specific `TextStreamRulesProbe` / `DomainExceptionMapProbe` rule table baked into driver defaults.** Driver-layer rule assertions were semantic judgement dressed up as observation: every driver hardcoded a list of `(regex, severity, code)` triples, which drifted with solver versions and produced false positives on real output. Deleted:
  - `fluent/driver.py` — `_FLUENT_STDERR_RULES` (3), `_FLUENT_TUI_STDOUT_RULES` (6), `_FLUENT_TRN_RULES` (alias), `_read_transcript` helper.
  - `comsol/driver.py` — `_COMSOL_STDERR_RULES` (6), `_COMSOL_EXC_MAP_RULES` (6).
  - `flotherm/driver.py` — `_FLOTHERM_STDERR_RULES` (2).
  - `workbench/driver.py` — `_WB_STDOUT_RULES` (5).
  - `mechanical/driver.py` — `_MECH_STDOUT_RULES` (3).
  - `lsdyna/driver.py` — `_LSDYNA_STDERR_RULES` (3).
  - `ansa/driver.py` — `_ANSA_STDOUT_RULES` (2).
  - `matlab/driver.py` — `_MATLAB_STDERR_RULES` (2), `_MATLAB_STDOUT_RULES` (2).
  - `cfx/driver.py` — `_CFX_STDOUT_RULES` (2).
  - `sim/inspect.py` — default `_EXC_MAP_RULES` (3 Fluent-specific entries) emptied to `[]`.

  Observable in real sessions: a plain CFX `list-objects` command went from 23 diagnostics (22 false-positive `cfx.post.internal_error` triggered by normal `/INTERNAL TABLE:` object names) down to 1 clean `sim.process.exit_zero`. Real errors still surface verbatim in `result["error"]` so an agent can read the actual text and decide.

  `TextStreamRulesProbe` and `DomainExceptionMapProbe` remain exported from `sim.inspect` as framework capabilities — skills or agents that want the old behaviour instantiate them explicitly with their own rules. We just no longer bake rules into every driver.

- **Test rewrites for the new contract.**
  - `tests/inspect/test_driver_probe_wiring.py` — parametrised over all 7 newly-wired session drivers; the old `test_solver_specific_rule_fires` (which asserted the regex hits) is replaced by `test_no_driver_level_rule_codes`, which feeds hostile text matching every old rule pattern into every driver's `run()` and asserts that **no** solver-prefixed codes (`wb.*`, `mech.*`, `lsdyna.*`, `cfx.*`, `matlab.*`, `ansa.*`, `fluent.*`, `comsol.java.*`, …) appear in the resulting diagnostics. 42/42 in ~0.2 s.
  - `tests/inspect/test_channel_3_4_5_9.py` — two Fluent-coupled assertions on `DomainExceptionMapProbe()` replaced with `test_exception_map_probe_default_rules_are_empty` (asserts zero output with default rules) and `test_exception_map_probe_applies_explicit_rules` (asserts the class still honours caller-supplied rules — guards the capability without wiring Fluent semantics in).

- **Real-solver validation after rule removal.** Full unit suite: 838 passed (2 pre-existing UUID failures in `tests/base/test_run.py` unrelated to probes). Real CFX `cfx5post -line` e2e on VMFL015: false-positive count dropped 22 → 0, real errors still visible in `result["error"]`. Real COMSOL `surface_mount_package` e2e: PASS, launch 31.7 s, 6/6 steps, `Tmax = 50.0 °C`.
