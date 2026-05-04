# Changelog

## 0.1.11 - 2026-05-04

- Prefer COMSOL `shared-desktop` mode for reliable live GUI collaboration.
- Add `session.health.live_model_binding` to show whether the driver model handle is bound to the Desktop active model tag.
- Warn when shared-desktop snippets create or switch to sidecar models that the visible COMSOL Desktop may not display.

## 0.1.10 - 2026-05-03

- Accept the sim-cli default `ui_mode=no_gui` as the canonical COMSOL no-visible-UI mode.

## 0.1.9 - 2026-05-03

- Tighten Desktop attach target discovery so browser pages mentioning `sim-plugin-comsol` are not mistaken for COMSOL Desktop.

## 0.1.8 - 2026-05-03

- Use `uvx --from sim-plugin-comsol sim-comsol-attach ...` as the documented COMSOL Desktop attach path so users and agents share the same invocation.
- Fix CI setup for the repo-local pytest basetemp directory.

## 0.1.7 - 2026-05-03

- Remove internal test-implementation wording from the public README/PyPI description.

## 0.1.6 - 2026-05-03

- Prepare public PyPI publishing through GitHub Trusted Publishing.
- Add the `sim-comsol-attach` helper for realtime-visible COMSOL Desktop collaboration.
- Update the bundled COMSOL skill to prefer Desktop attach for interactive Windows work.
