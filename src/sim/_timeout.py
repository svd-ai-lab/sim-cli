"""Windows-safe per-call timeout helper.

Used by session driver runtimes (Fluent / COMSOL) to keep a hung
solver RPC from blocking the whole sim server.

Design constraints:
  - Must work on Windows (no `signal.SIGALRM`).
  - Cannot isolate via subprocess (would lose the live session's
    in-process state — pyfluent holds an RPC client object,
    COMSOL/JPype pins a JVM).
  - Consequence: we can't *kill* a hung worker thread. We let it run
    as daemon and return to the caller with a `hung=True` marker; the
    caller is expected to tear down the session.

`timeout_s <= 0` (or None) means "no timeout enforced" — run to
completion. Default is 300s (5 min), generous enough for typical
iterate/solve calls but not infinite.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_TIMEOUT_S: float = 300.0


@dataclass
class TimeoutResult:
    """What `call_with_timeout` returns.

    Attributes:
        value:     callable's return value (None on exception OR hang)
        exception: the exception the callable raised, if any
        hung:      True iff we returned early because timeout fired
        elapsed_s: wall-clock seconds spent inside the call (capped at
                   `timeout_s` when hung=True)
        timeout_s: the timeout budget that was in effect
    """
    value: Any = None
    exception: BaseException | None = None
    hung: bool = False
    elapsed_s: float = 0.0
    timeout_s: float = 0.0

    def to_dict(self) -> dict:
        if self.hung:
            err = f"snippet exceeded timeout_s={self.timeout_s}"
        elif self.exception is not None:
            err = f"{type(self.exception).__name__}: {self.exception}"
        else:
            err = None
        return {
            "hung": self.hung,
            "elapsed_s": round(self.elapsed_s, 3),
            "timeout_s": self.timeout_s,
            "error": err,
        }


def call_with_timeout(
    fn: Callable[[], Any],
    timeout_s: float | None = DEFAULT_TIMEOUT_S,
) -> TimeoutResult:
    """Run `fn()` in a daemon thread; return TimeoutResult.

    If timeout_s is None/<=0, runs fn() inline with no timeout guarding.

    On timeout, the worker thread is abandoned (kept as daemon so the
    process can still exit). The caller MUST tear down the solver
    session after hung=True — otherwise subsequent RPC calls on the
    same session may deadlock.
    """
    if timeout_s is None or timeout_s <= 0:
        t0 = time.monotonic()
        try:
            value = fn()
            return TimeoutResult(
                value=value, hung=False,
                elapsed_s=time.monotonic() - t0,
                timeout_s=0.0,
            )
        except BaseException as exc:
            return TimeoutResult(
                exception=exc, hung=False,
                elapsed_s=time.monotonic() - t0,
                timeout_s=0.0,
            )

    box: dict = {"value": None, "exc": None, "done": False}

    def _worker():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["exc"] = exc
        finally:
            box["done"] = True

    t0 = time.monotonic()
    t = threading.Thread(target=_worker, daemon=True, name="sim.timeout.worker")
    t.start()
    t.join(timeout=timeout_s)
    elapsed = time.monotonic() - t0

    if not box["done"]:
        return TimeoutResult(
            value=None, exception=None, hung=True,
            elapsed_s=elapsed, timeout_s=timeout_s,
        )
    return TimeoutResult(
        value=box["value"], exception=box["exc"], hung=False,
        elapsed_s=elapsed, timeout_s=timeout_s,
    )
