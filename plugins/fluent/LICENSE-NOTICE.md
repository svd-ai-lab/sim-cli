# License notice

This plugin is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

**Users must supply their own Ansys Fluent license.** This plugin does **not**
bundle, embed, or redistribute any vendor SDK, Fluent binary, or licensed
content from Ansys. It is a thin Python adapter that:

- depends on the open-source [`ansys-fluent-core`](https://pypi.org/project/ansys-fluent-core/)
  SDK (MIT-licensed, distributed by Ansys via PyPI), and
- launches a Fluent process that the user has installed and licensed
  separately on their own host.

If you do not have a valid Ansys Fluent license, the driver's `connect()`
will succeed only on package availability, but `launch()` will fail when
Fluent itself rejects the unlicensed start.
