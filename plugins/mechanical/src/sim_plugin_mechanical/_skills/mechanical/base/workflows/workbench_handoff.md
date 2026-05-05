# Workbench to Mechanical handoff

Workbench owns Engineering Data, Geometry, and Model cells. Mechanical owns
setup, solution, and results. Before applying Mechanical loads, supports, mesh
controls, or result objects, confirm that the Mechanical session is attached to
the expected Workbench Model state.

## Checklist

1. On the Workbench side:

   ```bash
   sim inspect workbench.project.identity
   sim inspect workbench.systems.summary
   ```

2. Confirm the expected system exists and the Model cell is refreshed or open.
3. On the Mechanical side:

   ```bash
   sim inspect session.health
   sim inspect mechanical.project.identity
   sim inspect mechanical.model.summary
   ```

4. Continue only when Mechanical reports at least one expected analysis and a
   nonzero geometry/body count.
5. Apply Mechanical setup objects one layer at a time, inspecting after each
   step.

## Do not

- Do not add Mechanical supports or loads through Workbench journal guesses.
- Do not continue from a blank standalone Mechanical session when the user
  expects a Workbench-backed model.
- Do not treat screenshots as acceptance without structured model checks.
