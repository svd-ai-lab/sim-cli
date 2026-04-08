"""Fluent runner for the pyfluent_0_37_legacy profile.

Lives inside .sim/envs/pyfluent_0_37_legacy/. Spawned via:

    <env-python> -m sim._runners.fluent.pyfluent_037

This profile is the last one that supports Fluent 24.1 — pyfluent 0.38
dropped that solver version upstream. Runtime API divergences from the
pyfluent_0_38_modern profile (e.g. cell_zone.<x>.material vs
cell_zone.<x>.general.material) live here as we add per-profile façade
calls in a follow-up task.
"""
from __future__ import annotations

import sys

from sim._runners.fluent._common import FluentRunnerBase


class PyFluent037Runner(FluentRunnerBase):
    profile_name = "pyfluent_0_37_legacy"


def main() -> int:
    return PyFluent037Runner().run()


if __name__ == "__main__":
    sys.exit(main())
