# License Notice

`sim-plugin-comsol` is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

## Vendor software

This plugin is a **driver** — a thin adapter that lets sim-cli orchestrate
COMSOL Multiphysics. It does **not** bundle vendor binaries, the COMSOL
JVM/Java runtime, or the `mph` Python SDK.

Users must supply their own COMSOL Multiphysics license and installation;
this plugin does not bundle vendor binaries or SDKs. The `mph` Python
package (an independent open-source project on PyPI) is declared as a
runtime dependency but loaded lazily — the driver itself is import-safe
without it.

You are responsible for complying with COMSOL's license terms when using
this plugin to drive a COMSOL installation.
