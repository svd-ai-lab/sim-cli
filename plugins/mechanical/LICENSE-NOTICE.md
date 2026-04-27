# License notice

This plugin is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

**Users must supply their own Ansys Mechanical license.** This plugin does **not**
bundle, embed, or redistribute any vendor SDK, Mechanical binary, or licensed
content from Ansys. It is a thin Python adapter that:

- depends on the open-source [`ansys-mechanical-core`](https://pypi.org/project/ansys-mechanical-core/)
  SDK (MIT-licensed, distributed by Ansys via PyPI), and
- launches a Mechanical process (`AnsysWBU.exe`) that the user has installed
  and licensed separately on their own host.

If you do not have a valid Ansys Mechanical license, the driver's `connect()`
will succeed only on package availability, but `launch()` will fail when
Mechanical itself rejects the unlicensed start.
