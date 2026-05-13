# Skills Layering

This document records the current skill packaging model.

## Ownership

- `sim-cli` owns shared runtime skills under `src/sim/_skills/sim-cli/`.
- Solver plugins own solver-specific skills under their package-local
  `_skills/<solver>/` directory and expose them through the `sim.skills`
  entry-point group.
- A local `SIM_SKILLS_ROOT` can override plugin-bundled skills during
  development, but it is not the default public distribution path.

The old external shared-skill repository is archival. New public solver
workflow guidance should live with the plugin package that owns the driver.

## Runtime Sync

`sim plugin sync-skills` materializes:

1. the bundled `sim-cli` runtime skill, and
2. every installed plugin skill discoverable through `sim.skills`.

The command does not install packages. Agents add packages with `uv add`, then
sync and verify:

```bash
uv add sim-cli-core <plugin-package-spec>
uv run sim plugin sync-skills --target .agents/skills --copy
uv run sim check <solver>
uv run sim plugin doctor <solver> --deep
```

Use `.agents/skills` for Codex and GitHub Copilot. Use `.claude/skills` for
Claude Code.

## Layered Layout

Version-sensitive plugin skills may use this layout:

```text
_skills/<driver>/
  SKILL.md
  base/
  sdk/<sdk-slug>/
  solver/<solver-slug>/
```

`compatibility.yaml` can declare:

```yaml
profiles:
  - name: solver_2025_sdk_1
    solver_versions: ["2025"]
    sdk: ">=1,<2"
    active_sdk_layer: "1.x"
    active_solver_layer: "2025"
```

The `/connect` response includes `active_sdk_layer` and
`active_solver_layer` so an agent can pick the correct skill layer after the
Step-0 version probe.

## Validation

`verify_skills_layout(root, profiles)` checks that declared layers exist in an
explicit skills root. Plugin packages should also test that their packaged
`_skills/<solver>/SKILL.md` exists and that the `sim.skills` entry point loads.
