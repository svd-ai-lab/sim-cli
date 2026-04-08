"""Client side of the JSON-over-stdio runner protocol.

Lives in core ``sim``. Spawns a runner subprocess inside a profile env's
Python interpreter and exposes ``call(op, args)`` for the rest of sim core
to use.

Threading model: not thread-safe. One ``RunnerClient`` instance corresponds
to one subprocess and one logical session. The server's ``_state`` global
holds at most one of these at a time, mirroring the existing
single-session-per-server constraint.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path


class RunnerClientError(Exception):
    """Client-side IPC failure (subprocess died, JSON garbage, timeout)."""


class RunnerCallError(Exception):
    """Op handler returned ok=false. Carries type/message from the runner."""

    def __init__(self, op: str, error: dict):
        self.op = op
        self.error_type = error.get("type", "RunnerError")
        self.error_message = error.get("message", "")
        self.traceback = error.get("traceback")
        super().__init__(f"{self.error_type} during op={op!r}: {self.error_message}")


@dataclass(frozen=True)
class RunnerHandshake:
    sdk_version: str
    solver_version: str
    profile: str
    raw: dict


class RunnerClient:
    """One subprocess + a stdio JSON-RPC pair."""

    def __init__(
        self,
        *,
        env_python: Path,
        runner_module: str,
        cwd: Path | None = None,
        extra_env: dict | None = None,
    ):
        self.env_python = Path(env_python)
        self.runner_module = runner_module
        self.cwd = cwd
        self.extra_env = extra_env or {}

        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._handshake: RunnerHandshake | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_buf: list[str] = []

    # ── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> RunnerHandshake:
        """Spawn the subprocess and run the handshake.

        Returns the parsed handshake. Raises RunnerClientError if spawn or
        handshake fails.
        """
        if not self.env_python.is_file():
            raise RunnerClientError(f"runner python not found: {self.env_python}")

        argv = [str(self.env_python), "-m", self.runner_module]

        import os
        env = {**os.environ, **self.extra_env}
        # Force unbuffered stdio so JSON lines flush immediately. Even
        # though we use line-oriented JSON, Python's default buffering on
        # Windows can stall pipes.
        env["PYTHONUNBUFFERED"] = "1"

        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line-buffered
                cwd=str(self.cwd) if self.cwd else None,
                env=env,
            )
        except OSError as e:
            raise RunnerClientError(
                f"failed to spawn runner: {' '.join(shlex.quote(a) for a in argv)} — {e}"
            ) from e

        self._start_stderr_drainer()

        try:
            data = self.call("handshake", {})
        except Exception as e:
            self._terminate_silently()
            raise RunnerClientError(f"handshake failed: {e}") from e

        self._handshake = RunnerHandshake(
            sdk_version=data.get("sdk_version", "?"),
            solver_version=data.get("solver_version", "?"),
            profile=data.get("profile", "?"),
            raw=data,
        )
        return self._handshake

    def stop(self) -> None:
        """Send op=shutdown then wait briefly. Falls back to terminate."""
        if self._proc is None:
            return
        try:
            self.call("shutdown", {})
        except Exception:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._terminate_silently()
        finally:
            self._proc = None

    # ── core RPC ────────────────────────────────────────────────────────

    def call(self, op: str, args: dict | None = None, *, timeout: float | None = None) -> dict:
        """Send one op and wait for the matching response.

        timeout: optional float seconds for the read side. The default of
        None waits forever, which is what op=connect (which can take a
        minute to launch Fluent) needs.
        """
        if self._proc is None:
            raise RunnerClientError("runner is not running")
        if self._proc.poll() is not None:
            stderr = "".join(self._stderr_buf).strip()
            raise RunnerClientError(
                f"runner has exited (rc={self._proc.returncode}); stderr:\n{stderr}"
            )

        with self._lock:
            msg_id = self._next_id
            self._next_id += 1

            request = {"id": msg_id, "op": op, "args": args or {}}
            line = json.dumps(request, default=str) + "\n"

            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise RunnerClientError(f"runner stdin closed: {e}") from e

            # Naive synchronous read of one line. The runner is single-
            # threaded and processes messages in order, so this is fine.
            response_line = self._proc.stdout.readline()
            if not response_line:
                stderr = "".join(self._stderr_buf).strip()
                raise RunnerClientError(
                    f"runner produced no response; stderr:\n{stderr}"
                )

        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as e:
            raise RunnerClientError(
                f"runner emitted non-JSON line: {response_line!r}"
            ) from e

        if response.get("id") != msg_id:
            raise RunnerClientError(
                f"runner response id mismatch: sent {msg_id}, got {response.get('id')}"
            )

        if response.get("ok"):
            return response.get("data") or {}

        raise RunnerCallError(op, response.get("error") or {})

    # ── accessors ───────────────────────────────────────────────────────

    @property
    def handshake(self) -> RunnerHandshake | None:
        return self._handshake

    @property
    def stderr_text(self) -> str:
        return "".join(self._stderr_buf)

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # ── internals ───────────────────────────────────────────────────────

    def _start_stderr_drainer(self) -> None:
        """Drain the runner's stderr in the background so it never blocks."""
        if not self._proc or not self._proc.stderr:
            return

        def _drain():
            assert self._proc is not None
            assert self._proc.stderr is not None
            try:
                for chunk in self._proc.stderr:
                    self._stderr_buf.append(chunk)
            except Exception:
                pass

        t = threading.Thread(target=_drain, name="runner-stderr", daemon=True)
        t.start()
        self._stderr_thread = t

    def _terminate_silently(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception:
            pass


# ── convenience: spawn a runner for a bootstrapped profile ──────────────────


def spawn_runner_for_profile(profile_name: str) -> RunnerClient:
    """Look up a profile, ensure its env is bootstrapped, spawn its runner.

    Returns a started RunnerClient (handshake already done). Raises
    RunnerClientError if the env is missing or the spawn fails.

    Used by ``server.py`` ``/connect`` and by the CLI ``sim connect`` flow.
    """
    from sim import env_manager
    from sim.compat import find_profile

    state = env_manager.env_state(profile_name)
    if not state:
        raise RunnerClientError(
            f"profile env not bootstrapped: {profile_name}\n"
            f"  run:  sim env install {profile_name}"
        )

    found = find_profile(profile_name)
    if not found:
        raise RunnerClientError(f"unknown profile in any compatibility.yaml: {profile_name}")
    _, profile = found

    py = env_manager.env_python(profile_name)
    # Pass the profile name through so single-module runners (e.g.
    # sim._runners.openfoam.shell_runner serving every openfoam_v* profile)
    # can self-bind without needing one module per profile.
    client = RunnerClient(
        env_python=py,
        runner_module=profile.runner_module,
        extra_env={"SIM_RUNNER_PROFILE": profile_name},
    )
    client.start()
    return client
