# Workbench to Mechanical handoff

Workbench owns the project scaffold. Mechanical owns setup, solve, and
results. Keep the boundary clear so the agent does not add boundary conditions
through Workbench journals or create a blank standalone Mechanical session when
the user expects the Workbench Model cell.

## Static Structural handoff

1. In Workbench, create or update the Static Structural system.
2. Refresh Engineering Data, Geometry, and Model as needed.
3. Inspect:

   ```bash
   uv run sim inspect workbench.project.identity
   uv run sim inspect workbench.systems.summary
   ```

4. Save or update a project checkpoint before opening Mechanical.
5. In Mechanical, inspect:

   ```bash
   uv run sim inspect session.health
   uv run sim inspect mechanical.project.identity
   uv run sim inspect mechanical.model.summary
   ```

6. Continue only when Mechanical sees the expected analysis tree and non-empty
   geometry/body state.

## Acceptance

- Workbench reports the expected system and standard cells.
- The Model cell has been refreshed or intentionally opened.
- Mechanical reports at least one analysis for the intended system.
- Mechanical geometry/body count is nonzero before applying supports or loads.
- Any solve/result extraction happens through the Mechanical plugin, not through
  Workbench journal guesses.
