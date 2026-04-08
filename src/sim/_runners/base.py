"""Base class for sim driver runners.

A runner subclass implements ``op_<name>`` methods (handshake, connect,
exec, inspect, disconnect, shutdown) and calls ``RunnerLoop.run()`` from
its ``__main__`` block. This module then handles the JSON-over-stdio loop,
error packaging, and lifecycle.

Wire protocol (one JSON object per line, both directions):

    request:   {"id": int, "op": str, "args": dict}
    success:   {"id": int, "ok": true,  "data": <any>}
    error:     {"id": int, "ok": false, "error": {"type": str, "message": str}}

Reserved ops:
    handshake  → must return {"sdk_version", "solver_version", "profile"}
    shutdown   → no return; runner exits cleanly after ack

See ``docs/architecture/version-compat.md`` §8 for the full spec.
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any


class RunnerError(Exception):
    """Raised by an op handler to send a structured error to the core process."""

    def __init__(self, message: str, *, type: str = "RunnerError"):
        super().__init__(message)
        self.type = type


class RunnerLoop:
    """Subclass me. Implement op_<name> methods. Call run() from __main__.

    Lifecycle expectations:
      - The first message MUST be op=handshake. The base loop enforces this.
      - After handshake, any number of op=connect/exec/inspect/disconnect.
      - op=shutdown is the polite way to exit. EOF on stdin is also accepted.
    """

    profile_name: str = "<unset>"  # subclasses set this

    def __init__(self) -> None:
        self._handshake_done = False
        self._stdin = sys.stdin
        self._stdout = sys.stdout

    # ── public entry point ──────────────────────────────────────────────

    def run(self) -> int:
        """Main loop. Returns process exit code."""
        try:
            for line in self._read_lines():
                if not line.strip():
                    continue
                self._handle_line(line)
        except KeyboardInterrupt:
            return 130
        except Exception:
            # Unexpected crash in the loop itself (not inside an op handler).
            # Try to surface it via stderr; the parent will read it from the
            # subprocess's stderr handle.
            traceback.print_exc(file=sys.stderr)
            return 1
        return 0

    # ── op handlers (subclasses override) ───────────────────────────────

    def op_handshake(self, args: dict) -> dict:
        """Return {sdk_version, solver_version, profile}.

        Subclasses MUST override and import their SDK here (this is the
        moment we accept the cost of loading the heavy package). If the
        SDK can't be imported, raise RunnerError so the core process gets
        a clean error response instead of a crash.
        """
        raise NotImplementedError

    def op_connect(self, args: dict) -> dict:
        raise NotImplementedError

    def op_exec(self, args: dict) -> dict:
        raise NotImplementedError

    def op_inspect(self, args: dict) -> dict:
        raise NotImplementedError

    def op_disconnect(self, args: dict) -> dict:
        raise NotImplementedError

    def op_shutdown(self, args: dict) -> dict:
        # Default: just acknowledge. Subclasses can override to clean up.
        return {"goodbye": True}

    # ── internals ───────────────────────────────────────────────────────

    def _read_lines(self):
        for line in self._stdin:
            yield line

    def _handle_line(self, raw_line: str) -> None:
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError as e:
            self._write({
                "id": None,
                "ok": False,
                "error": {"type": "JSONDecodeError", "message": str(e)},
            })
            return

        msg_id = msg.get("id")
        op = msg.get("op")
        args = msg.get("args") or {}

        if not op:
            self._write({
                "id": msg_id,
                "ok": False,
                "error": {"type": "BadRequest", "message": "missing 'op' field"},
            })
            return

        # Enforce handshake-first contract
        if not self._handshake_done and op != "handshake":
            self._write({
                "id": msg_id,
                "ok": False,
                "error": {
                    "type": "ProtocolError",
                    "message": f"expected op=handshake first, got op={op!r}",
                },
            })
            return

        handler = getattr(self, f"op_{op}", None)
        if handler is None:
            self._write({
                "id": msg_id,
                "ok": False,
                "error": {"type": "UnknownOp", "message": f"unknown op: {op!r}"},
            })
            return

        try:
            data: Any = handler(args)
        except RunnerError as e:
            self._write({
                "id": msg_id,
                "ok": False,
                "error": {"type": e.type, "message": str(e)},
            })
            return
        except Exception as e:
            self._write({
                "id": msg_id,
                "ok": False,
                "error": {
                    "type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                },
            })
            return

        if op == "handshake":
            self._handshake_done = True

        self._write({"id": msg_id, "ok": True, "data": data})

        if op == "shutdown":
            # Flush is automatic (line buffered) but be defensive
            self._stdout.flush()
            sys.exit(0)

    def _write(self, payload: dict) -> None:
        line = json.dumps(payload, default=str)
        self._stdout.write(line + "\n")
        self._stdout.flush()
