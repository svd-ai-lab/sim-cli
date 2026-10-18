# sim-plugin-spaceclaim

SpaceClaim skill package for Codex/sim workflows.

This first version intentionally ships guidance and local discovery utilities,
not a full sim driver. SpaceClaim is valuable for CAD preparation, repair,
fluid-domain/enclosure extraction planning, and solver handoff, but many useful
operations still depend on geometry selections that should be confirmed from
the model.

## Contents

- `skills/spaceclaim/SKILL.md` - bundled agent skill source.
- `skills/spaceclaim/scripts/probe_spaceclaim.ps1` -
  Windows discovery helper for local SpaceClaim installs and API docs.
- `.codex-plugin/plugin.json` - local Codex plugin manifest for direct plugin use.
