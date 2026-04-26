"""Allow ``python -m sim ...`` invocation (equivalent to the ``sim`` console script).

Why this exists
---------------
The console script ``sim`` (declared in ``[project.scripts]``) is the canonical
entry point for end users — it stays unchanged. This module forwards
``python -m sim ...`` to the same Click group so developers have a second
invocation that does *not* hold a Windows file lock on
``.venv/Scripts/sim.exe``.

That lock is the whole reason this file exists: with the editable install,
``uv sync`` rewrites ``Scripts/sim.exe`` on every sync, but a running
``sim serve`` has the exe open, so Windows refuses the rewrite (``os error
32``) and the entire sync aborts. Launching the dev server as
``python -m sim serve --reload`` instead means the running process holds
``python.exe`` (uv-managed, shared, not project-managed), and ``sim.exe``
stays free for ``uv sync`` to rewrite while iteration proceeds.

Same pattern used by pip, ruff, pytest, etc.
"""
from sim.cli import main

if __name__ == "__main__":
    main()
