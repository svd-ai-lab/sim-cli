"""Unit tests — Windows-safe snippet-timeout helper.

Used by PyFluentRuntime.exec_snippet and ComsolDriver.run to keep a hung
Fluent/COMSOL RPC from blocking the whole sim server.

Design:
  - Thread-based (no signal.alarm — Windows incompatible).
  - On timeout: caller gets a synthetic TimeoutError-style return;
    the hung thread is abandoned (daemon) — acceptable since the caller
    is expected to disconnect the whole session afterward.
"""
from __future__ import annotations

import threading
import time

import pytest


def test_call_with_timeout_returns_on_success():
    from sim._timeout import call_with_timeout

    result = call_with_timeout(lambda: "ok", timeout_s=2.0)
    assert result.hung is False
    assert result.value == "ok"
    assert result.exception is None
    assert result.elapsed_s >= 0.0
    assert result.elapsed_s < 2.0


def test_call_with_timeout_propagates_exception():
    from sim._timeout import call_with_timeout

    def _boom():
        raise ValueError("nope")

    result = call_with_timeout(_boom, timeout_s=1.0)
    assert result.hung is False
    assert result.value is None
    assert isinstance(result.exception, ValueError)
    assert "nope" in str(result.exception)


def test_call_with_timeout_marks_hung_when_exceeds_deadline():
    from sim._timeout import call_with_timeout

    def _slow():
        time.sleep(3.0)
        return "should never return in time"

    t0 = time.time()
    result = call_with_timeout(_slow, timeout_s=0.3)
    wall = time.time() - t0

    assert result.hung is True
    assert result.value is None
    # the helper MUST return well before the slow call would have finished
    assert wall < 2.0, f"timeout helper itself blocked for {wall}s"
    # elapsed_s reports what was measured up to the timeout decision;
    # allow small scheduler jitter on Windows (may return ~5ms early)
    assert result.elapsed_s >= 0.25, f"elapsed too small: {result.elapsed_s}"


def test_call_with_timeout_default_is_generous():
    """Sanity: default timeout lets short ops finish without spurious hangs."""
    from sim._timeout import call_with_timeout

    result = call_with_timeout(lambda: 42)  # no explicit timeout
    assert result.hung is False
    assert result.value == 42


def test_call_with_timeout_zero_or_negative_treated_as_disabled():
    """timeout_s <= 0 means 'no timeout enforced'."""
    from sim._timeout import call_with_timeout

    def _sleep_briefly():
        time.sleep(0.1)
        return "done"

    result = call_with_timeout(_sleep_briefly, timeout_s=0)
    assert result.hung is False
    assert result.value == "done"

    result = call_with_timeout(_sleep_briefly, timeout_s=-1)
    assert result.hung is False
    assert result.value == "done"


def test_timeout_result_to_dict_for_diagnostic_consumption():
    """The result object must be easy for probe callers to inspect."""
    from sim._timeout import call_with_timeout

    result = call_with_timeout(lambda: None, timeout_s=1.0)
    d = result.to_dict()
    assert "hung" in d and "elapsed_s" in d and "error" in d
    # on success: error is None (no exception); hung is False
    assert d["hung"] is False and d["error"] is None


def test_timeout_result_to_dict_on_hang():
    from sim._timeout import call_with_timeout

    def _slow():
        time.sleep(2.0)

    result = call_with_timeout(_slow, timeout_s=0.2)
    d = result.to_dict()
    assert d["hung"] is True
    assert isinstance(d["error"], str) and "0.2" in d["error"]
