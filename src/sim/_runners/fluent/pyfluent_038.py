"""Fluent runner for the pyfluent_0_38_modern profile.

Lives inside .sim/envs/pyfluent_0_38_modern/. Spawned via:

    <env-python> -m sim._runners.fluent.pyfluent_038

PyFluent 0.38 differences from 0.37 (e.g. .general.material accessor) live
here when they affect runtime behavior. For M1 the difference is purely the
SDK version pinned in the env; runtime API divergence will land as we add
profile-specific façade calls in a follow-up task.
"""
from __future__ import annotations

import sys

from sim._runners.fluent._common import FluentRunnerBase


class PyFluent038Runner(FluentRunnerBase):
    profile_name = "pyfluent_0_38_modern"


def main() -> int:
    return PyFluent038Runner().run()


if __name__ == "__main__":
    sys.exit(main())
