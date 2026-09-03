"""Opt-in real AEDT smoke for timeout preservation and exact-PID reattachment."""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

import sim_plugin_hfss.driver as drv
from sim_plugin_hfss import HfssDriver


if os.environ.get("SIM_HFSS_RUN_TIMEOUT_RECOVERY_SMOKE") != "1":
    pytest.skip(
        "set SIM_HFSS_RUN_TIMEOUT_RECOVERY_SMOKE=1 to run the real recovery smoke",
        allow_module_level=True,
    )


def test_real_hfss_control_timeout_preserves_and_reattaches_exact_pid() -> None:
    owner = HfssDriver()
    attached = HfssDriver()
    owned_pid: int | None = None
    attached_hfss: Any | None = None

    try:
        launched = owner.launch(ui_mode="no_gui", close_on_exit=False)
        assert launched["ok"], launched
        owned_pids = launched["owned_aedt_pids"]
        assert len(owned_pids) == 1, launched
        owned_pid = owned_pids[0]

        timed = owner.run(
            "import time\ntime.sleep(1.0)",
            label="real-timeout-recovery-smoke",
            timeout_s=0.1,
        )
        assert timed["hung"] is True, timed
        assert timed["quarantined"] is True, timed
        health = owner.query("session.health")
        assert health["code"] == "hfss.session.quarantined", health
        assert health["owned_aedt_pid_alive"] == {str(owned_pid): True}, health

        # The timed-out worker cannot be cancelled. Wait until this synthetic
        # control call has returned before opening another PyAEDT handle.
        time.sleep(1.1)
        detached = owner.disconnect()
        assert detached["cleanup"]["solver_process_preserved"] is True, detached
        assert drv._pid_is_alive(owned_pid)

        reattached = attached.launch(
            ui_mode="no_gui",
            new_desktop=False,
            aedt_process_id=owned_pid,
            close_on_exit=False,
        )
        assert reattached["ok"], reattached
        assert reattached["aedt_pid"] == owned_pid, reattached
        assert attached.query("session.health")["connected"] is True

        attached_hfss = attached._hfss
        disconnected = attached.disconnect()
        assert disconnected["cleanup"]["close_desktop"] is False, disconnected
        assert drv._pid_is_alive(owned_pid)
    finally:
        # This smoke owns the exact process it created. Close that one desktop;
        # use a PID-specific fallback only if PyAEDT cannot release it.
        if attached_hfss is not None:
            try:
                attached_hfss.release_desktop(close_projects=False, close_desktop=True)
            except Exception:
                pass
        if owned_pid is not None:
            time.sleep(1.0)
            if drv._pid_is_alive(owned_pid):
                drv._kill_pid(owned_pid)
