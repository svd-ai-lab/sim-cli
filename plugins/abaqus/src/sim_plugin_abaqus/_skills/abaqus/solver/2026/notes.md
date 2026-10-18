# Abaqus 2026 Version Notes

## Installation

- Commands dir convention: `SIMULIA\Commands\abaqus.bat` often wraps the
  versioned launcher such as `abq2026.bat`.
- Confirm the active local build with `abaqus information=release` or
  `uv run sim check abaqus` before making release-specific claims.

## Key Changes from 2025

- Python 3.x embedded interpreter (continued from 2024)
- SIM architecture for solver (replaces legacy .fil format internally)
- Enhanced contact algorithm performance

## Tested Capabilities

| Capability | Status | Notes |
|------------|--------|-------|
| `*STATIC` analysis | Verified | Cantilever beam E2E passed |
| `.inp` input decks | Verified | Keywords parsed correctly |
| `NODE PRINT` output | Verified | Displacement values in `.dat` |
| `interactive` mode | Verified | Waits for completion before returning |
| License checkout | Environment-specific | Do not record token counts or entitlement details in public logs |

## Version Detection

The driver detects this version via:
1. `abq2026.bat` filename maps to version "2026".
2. `abaqus information=release` reports "Abaqus 2026" in stdout.
