# Simcenter Flotherm 2410 (2024.3) notes

Tested 2026-04-12 alongside 2504.

## Same behavior as 2504

- GUI automation via `feat/flotherm-gui-automation` branch works
  (Project > Import Project > Pack File → Macro > Play FloSCRIPT → solve)
- FloSCRIPT Drawing-Board syntax (`project_unlock` + `project_load` +
  `<start start_type="solver"/>`) works when project is registered
- Same directory layout: `WinXP/bin/flotherm.bat`,
  `WinXP/bin/flotherm.exe`, `WinXP/bin/floserv.exe`,
  `WinXP/bin/translator.exe`, `WinXP/bin/solexe.exe`
- `group.cat` registration still required for FloSCRIPT `project_load`

## Same failures as 2504 (see `../../known_issues.md`)

- `flotherm.bat -b` — batch mode broken upstream (RunTable exception)
- `flotherm.bat -f` — CLI FloSCRIPT playback silently dropped
- `translator.exe` + `solexe.exe` headless path — **can crash with
  0xC0000005 (access violation)** in Windows headless/session-0
  contexts. Same symptom has been observed on 2504. See [sim-cli#14].

## No version-specific deltas discovered yet

The driver (`sim.drivers.flotherm`) detects 2410 via
`find_installation()` identically to 2504 — `extract_version()` parses
the `2410` from the install path with no special handling.

[sim-cli#14]: https://github.com/svd-ai-lab/sim-cli/issues/14
