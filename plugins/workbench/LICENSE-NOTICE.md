# Notice

This plugin is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

This plugin does not bundle, embed, or redistribute Ansys Workbench, Ansys
SDK packages, vendor binaries, or vendor content. It is a Python adapter that:

- depends on the open-source `ansys-workbench-core` SDK distributed by Ansys,
  and
- launches a Workbench process (via `launch_workbench` or `RunWB2.exe`) that
  the user has installed separately.

Users are responsible for satisfying all vendor software prerequisites for
their own environment.
