# License notice

This plugin is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

**Users must supply their own Dassault Systemes SIMULIA Abaqus license.**
This plugin does **not** bundle, embed, or redistribute any vendor SDK,
Abaqus binary, or licensed content from Dassault Systemes. It is a thin
Python adapter that:

- depends only on `sim-runtime` (the open-source sim-cli runtime), and
- launches an Abaqus process (`abaqus.bat` / `abqNNNN.bat`) that the user
  has installed and licensed separately on their own host.

There is no Python SDK dependency — Abaqus exposes no system-Python SDK;
its scripting interface lives inside its own embedded interpreter, which
this driver invokes via `abaqus cae noGUI=<file>` for `.py` scripts and
`abaqus job=<name> input=<file> interactive` for `.inp` decks.

If you do not have a valid Abaqus license, the driver's `connect()` may
still report `ok` based on installation detection, but `run_file()` will
fail when Abaqus itself rejects the unlicensed start.
