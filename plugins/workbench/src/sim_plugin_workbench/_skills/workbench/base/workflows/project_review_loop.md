# Workbench project review loop

Use this loop for every non-trivial Workbench project. Workbench creates the
project structure that downstream solver plugins rely on, so a small cell-state
mistake can become a Mechanical setup or solve failure later.

## Loop

1. Inspect `uv run sim inspect session.health`.
2. Inspect `uv run sim inspect workbench.project.identity`.
3. Inspect `uv run sim inspect workbench.systems.summary`.
4. Before creating a system, inspect `uv run sim inspect workbench.templates.visible`
   and `uv run sim inspect "workbench.templates.resolve:<workflow intent>"`.
5. For long-running update/refresh/open-model steps, capture a screenshot
   before the call and monitor with screenshots plus structured inspect data.
6. Execute one bounded journal step using the resolved live template or an
   already-present system.
7. Inspect `uv run sim inspect last.result`.
8. Re-inspect `workbench.systems.summary`.
9. Save or update a project checkpoint before handoff or risky edits.
10. Continue only when the system and cell state match the intended workflow.

## Checkpoints

| Layer | Expected evidence |
|---|---|
| Project | Session health is ok; a project checkpoint or saved project name is known when the work is durable. |
| Templates | Live resolver found a creatable template, or the missing template/product is reported explicitly. |
| Systems | The expected analysis system exists and has the expected cell set. |
| Engineering Data | Materials needed by downstream solver setup are present or intentionally deferred. |
| Geometry | Geometry cell is present and refreshed before opening the Model cell. |
| Model | Model cell is available for the solver handoff. |
| Handoff | Workbench side has a refreshed Model cell; Mechanical confirms the analysis tree before adding setup objects. |

Screenshots are required evidence for GUI progress, modal dialogs, and
interrupted long-running steps. `workbench.systems.summary` and the journal JSON
result remain the primary acceptance signals for project state.
