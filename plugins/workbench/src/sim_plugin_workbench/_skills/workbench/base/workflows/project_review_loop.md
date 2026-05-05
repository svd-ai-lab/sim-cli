# Workbench project review loop

Use this loop for every non-trivial Workbench project. Workbench creates the
project structure that downstream solver plugins rely on, so a small cell-state
mistake can become a Mechanical setup or solve failure later.

## Loop

1. Inspect `sim inspect session.health`.
2. Inspect `sim inspect workbench.project.identity`.
3. Inspect `sim inspect workbench.systems.summary`.
4. Execute one bounded journal step.
5. Inspect `sim inspect last.result`.
6. Re-inspect `workbench.systems.summary`.
7. Save or update a project checkpoint before handoff or risky edits.
8. Continue only when the system and cell state match the intended workflow.

## Checkpoints

| Layer | Expected evidence |
|---|---|
| Project | Session health is ok; a project checkpoint or saved project name is known when the work is durable. |
| Systems | The expected analysis system exists and has the expected cell set. |
| Engineering Data | Materials needed by downstream solver setup are present or intentionally deferred. |
| Geometry | Geometry cell is present and refreshed before opening the Model cell. |
| Model | Model cell is available for the solver handoff. |
| Handoff | Workbench side has a refreshed Model cell; Mechanical confirms the analysis tree before adding setup objects. |

Screenshots help with human review, but `workbench.systems.summary` and the
journal JSON result are the primary acceptance signals.
