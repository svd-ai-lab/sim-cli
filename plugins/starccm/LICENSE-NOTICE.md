# License notice

This plugin is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

**Users must supply their own Siemens Simcenter STAR-CCM+ license.** This
plugin does **not** bundle, embed, or redistribute any vendor SDK,
STAR-CCM+ binary, or licensed content from Siemens. It is a thin Python
adapter that:

- ships no STAR-CCM+ source, libraries, or Java APIs (Java macros are
  authored against the user's own local STAR-CCM+ install), and
- launches the `starccm+` (or `starccm+.bat` on Windows) batch executable
  that the user has installed and licensed separately on their own host.

If you do not have a valid STAR-CCM+ license, the driver's `connect()` may
still succeed when the binary is on disk, but `run_file()` will fail when
the STAR-CCM+ launcher rejects the unlicensed start (typically with a
"Licensing problem:" message in stderr).
