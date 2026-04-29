# Surface-Mount Package Heat Transfer Demo

Reproduces [COMSOL Application Library model 847](https://www.comsol.com/model/heat-transfer-in-a-surface-mount-package-for-a-silicon-chip-847):
**Heat Transfer in a Surface-Mount Package for a Silicon Chip**.

A silicon chip in a plastic surface-mount package sits on an FR4 circuit
board near a hot voltage regulator (50 °C). The chip dissipates ~20 mW
internally. Thin copper layers (ground plate and interconnect) provide
lateral heat spreading. Forced convection (h = 50 W/(m²·K), T_amb = 30 °C)
cools the exterior surfaces.

**Results:** chip max temperature = 45.8 °C (reference: 47.7 °C) — the
device does not overheat. The ~2 °C difference is due to simplified pin
geometry (L-shaped blocks vs original bent hexahedrons).

## Running with sim

```bash
# 1. Start sim serve on a Windows host from an interactive desktop session
# 2. Connect in standalone mode (simpler, no server subprocess)
sim --host <host> connect --solver comsol --ui-mode standalone

# 3. Build model step by step
sim --host <host> exec --file workflows/surface_mount_package/00_create_geometry.py
sim --host <host> exec --file workflows/surface_mount_package/01_assign_materials.py
sim --host <host> exec --file workflows/surface_mount_package/02_setup_physics.py
sim --host <host> exec --file workflows/surface_mount_package/03_generate_mesh.py
sim --host <host> exec --file workflows/surface_mount_package/04_solve.py
sim --host <host> exec --file workflows/surface_mount_package/05_plot_results.py

# 4. Disconnect when done
sim --host <host> disconnect
```

> **Visual verification:** Standalone mode has no GUI window. The workflow
> saves `surface_mount_package.mph` to the Desktop after each major step.
> Open it in COMSOL Desktop to inspect geometry, mesh, and results.
>
> For client-server mode (`--ui-mode gui`), use
> *File > Import Application from Server* after each step.

## Snippets

| Step | File | Description |
|------|------|-------------|
| 0 | `00_create_geometry.py` | PC board, package body, 16 L-shaped pins, chip, work planes |
| 1 | `01_assign_materials.py` | Aluminum (all, overridden), FR4, Plastic, Silicon, Copper |
| 2 | `02_setup_physics.py` | Heat Transfer: source, convection, fixed T, 2 thin layers |
| 3 | `03_generate_mesh.py` | Fine global + extra-fine on regulator & ground plate (~8.5k elems) |
| 4 | `04_solve.py` | Stationary study (~6s solve) |
| 5 | `05_plot_results.py` | Surface, slice, and chip-surface temperature plots |

## Model details

- **Source:** COMSOL Application Library model 847 (geometry from PDF spec)
- **Physics:** Heat Transfer in Solids (steady-state)
- **Length unit:** mm
- **Key feature:** Thin Layer boundary condition for copper ground plate
  (0.1 mm) and interconnect trace (5 µm) — avoids meshing sub-mm layers
  as 3D volumes
- **Geometry simplification:** Pins are L-shaped blocks (horizontal +
  vertical) instead of the original hexahedron + revolve + extrude chain.
  Thermal behavior is equivalent since cross-section and path length match.
- **Selection strategy:** Ball/Box selections created in the materials step
  are reused by physics and plots (COMSOL doesn't auto-create named
  geometry selections via the Java API)
