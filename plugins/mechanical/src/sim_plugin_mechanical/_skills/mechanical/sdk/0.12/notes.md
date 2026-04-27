# PyMechanical 0.12.x — layer notes

Active for sim profile `mechanical_v24_1_sdk` (and 24.2/25.1 fallbacks).

## What's here

- `ansys.mechanical.core.launch_mechanical(...)` — the remote launcher.
- `Mechanical` client with `run_python_script`, `upload`, `download`,
  `download_project`, `list_files`.
- `wait_till_mechanical_is_ready` — call after launch, always.

## Key signature for 0.12

```python
launch_mechanical(
    version=241,           # int, not str — "24.1" → 241
    batch=False,           # False = GUI visible
    cleanup_on_exit=False, # let the driver own teardown
    start_timeout=120,
)
```

## What 0.12 has that 0.11 doesn't

- `download_project()` — recursive project tree pull.
- Better timeout handling on `wait_till_mechanical_is_ready`.

## What 0.12 lacks (vs 0.13+)

- No built-in Chinese locale handling (see `known_issues.md` #1).
- `list_files()` is shallow (one directory only).

## Compat gotcha

`ansys-mechanical-core 0.12.x` requires `ansys-pythonnet>=3.1.0rc6`
(runtime DLL loading). The repo pin is already in `pyproject.toml`.
