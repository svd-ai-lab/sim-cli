"""sim driver runners — process boundary between core sim and live SDKs.

Each runner module is a small JSON-over-stdio server that lives INSIDE a
profile env (e.g. `.sim/envs/pyfluent_0_38_modern/`). The core `sim` process
spawns a runner via the env's Python interpreter and forwards
connect/exec/inspect/disconnect calls to it.

This separation lets the core sim process stay completely SDK-free, which
means: (a) `sim` startup time is unaffected by SDK weight, (b) a bug inside
PyFluent / mph / matlabengine cannot crash sim core, and (c) multiple
profile envs can coexist on one machine without dependency conflicts.

Architecture: ``docs/architecture/version-compat.md`` §8.
"""
