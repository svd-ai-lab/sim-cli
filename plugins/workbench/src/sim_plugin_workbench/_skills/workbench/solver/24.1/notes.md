# Ansys 24.1 (2024 R1) Notes

> Solver: Ansys Workbench 2024 R1 (v241)
> SDK: ansys-workbench-core 0.4–0.9 only

## SDK compatibility

- SDK 0.4–0.9: fully compatible
- SDK 0.10+: **refuses to connect** (hardcoded version gate)
- RunWB2 fallback: always works

## IronPython version

- IronPython 2.7 on .NET Framework 4.x
- Python 2.7 syntax only (no f-strings, no `:=` walrus)
- Some Python 3 stdlib modules unavailable (`pathlib`, `dataclasses`)

## Known quirks

1. **UnicodeEncodeError on `.DisplayText`**: System display names can
   contain .NET Unicode strings that fail `str()` conversion on
   Chinese/Japanese locale. Use fixed strings instead.

2. **No `ReturnValue()` support**: IronPython in 24.1 does not support
   `ReturnValue()` for passing data back through `run_script_string()`.
   Use the file-based result convention (`%TEMP%/sim_wb_result.json`).

3. **`codecs.open()` required**: Plain `open()` may use GBK encoding on
   Chinese Windows. Always use `codecs.open(path, "w", "utf-8")`.
