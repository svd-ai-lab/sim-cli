# License notice

This plugin is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

**Users must supply their own Ansys Workbench license.** This plugin does **not**
bundle, embed, or redistribute any vendor SDK, Workbench binary, or licensed
content from Ansys. It is a thin Python adapter that:

- depends on the open-source [`ansys-workbench-core`](https://pypi.org/project/ansys-workbench-core/)
  SDK (MIT-licensed, distributed by Ansys via PyPI), and
- launches a Workbench process (via `launch_workbench` or `RunWB2.exe`) that
  the user has installed and licensed separately on their own host.

If you do not have a valid Ansys Workbench license, the driver's `connect()`
will succeed only on package availability, but `launch()` will fail when
Workbench itself rejects the unlicensed start.
