# Workspace maintenance

Core runtime lives in `src/sim`; each independently published plugin lives in
`plugins/<solver>`. Keep the entry-point interface and plugin `_skills/` paths.
`simparse` is a separate PyPI dependency; do not vendor its implementation.

Use `uv sync --locked --all-packages --group dev`, then
`uv run --no-sync python scripts/workspace.py test`. Tests run in separate
processes per package. Public tests use unit tests and tiny synthetic fixtures.
Solver execution cases and detailed regression data belong in private
`sim-proj/cases/`; do not add them here.

Regenerate `plugin-index.json` with `uv run python scripts/workspace.py index`
after package metadata changes. Check it with `--check`.

Build one package with `uv build --no-sources --package <distribution>`.
Core releases use `v<version>` and `publish.yml`; plugin releases use
`<solver>-v<version>` and `plugin-publish.yml`, each matching package metadata.
Never combine sibling distributions in one publication artifact set.
