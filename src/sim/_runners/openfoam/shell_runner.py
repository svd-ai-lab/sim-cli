"""OpenFOAM shell runner — SDK-less runner for the openfoam_v* profiles.

OpenFOAM has no Python binding. The "SDK" is the bashrc that ships with the
solver: source it once to populate WM_PROJECT_DIR, FOAM_TUTORIALS, PATH, etc.,
and from then on every solver binary (blockMesh, simpleFoam, pisoFoam, …) is
available on PATH.

This runner mirrors that workflow over the JSON-over-stdio protocol:

  handshake -> probe WM_PROJECT_VERSION (and friends), report which OpenFOAM
               install we are bound to. Does NOT source bashrc here — that
               happens lazily in op_connect/op_exec.

  connect   -> source the bashrc once and snapshot the resulting environment
               into self._foam_env (a dict[str, str]). All subsequent
               op_exec calls run bash subshells with this env preloaded.

  exec      -> run a bash snippet under self._foam_env, capturing stdout /
               stderr / exit code. The snippet may also be a list of commands
               separated by newlines — bash handles that natively.

  inspect   -> session.summary / last.result / session.versions

  disconnect-> drop the snapshot, count it as cleanup.

Spawned via:

    <env-python> -m sim._runners.openfoam.shell_runner

Inside .sim/envs/openfoam_v<XXXX>/. The env's python is only used as an
exec host — OpenFOAM itself is not a Python package.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from sim._runners.base import RunnerError, RunnerLoop


# Profile-name → (default WM_PROJECT_VERSION substring) used as a hint when
# multiple installs exist on the host. The runner is spawned with the
# profile fixed at module level (one per yaml profile), so we know which
# version we should be binding to.
_PROFILE_VERSION_HINTS: dict[str, str] = {
    "openfoam_v2406": "v2406",
    "openfoam_v2312": "v2312",
    "openfoam_v2206": "v2206",
}


def _candidate_install_dirs() -> list[Path]:
    """Filesystem locations where ESI / Foundation OpenFOAM typically lives.

    Pure Path probing — no IO until the caller iterates. Returned in priority
    order; deduped by the caller.
    """
    bases: list[Path] = []
    # ESI default install on Ubuntu / Debian / RHEL
    for base in (Path("/opt"), Path("/usr/lib"), Path.home() / "OpenFOAM"):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            n = child.name.lower()
            if "openfoam" in n or n.startswith("openfoam-"):
                bases.append(child)
    return bases


def _bashrc_inside(install_dir: Path) -> Path | None:
    """ESI lays bashrc at <install>/etc/bashrc. Foundation lays it the same."""
    candidate = install_dir / "etc" / "bashrc"
    if candidate.is_file():
        return candidate
    # Some packages have an extra OpenFOAM-<ver>/ subdirectory
    for child in install_dir.iterdir() if install_dir.is_dir() else []:
        cand = child / "etc" / "bashrc"
        if cand.is_file():
            return cand
    return None


def _detect_install_for_profile(profile_name: str) -> tuple[Path, Path] | None:
    """Pick (install_dir, bashrc_path) for the runner's bound profile.

    Strategy:
      1. If WM_PROJECT_DIR is already set in the inherited env AND the
         resolved version matches the profile hint, use it.
      2. Otherwise scan the standard install dirs and pick the first
         whose name matches the profile hint.
      3. Otherwise (no hint match) pick the first viable install_dir
         we can find. The handshake will report whatever version comes
         out of bashrc — the resolver layer is responsible for refusing
         a mismatch upstream.
    """
    hint = _PROFILE_VERSION_HINTS.get(profile_name, "")

    # 1) Already-sourced env
    env_dir = os.environ.get("WM_PROJECT_DIR")
    if env_dir:
        p = Path(env_dir)
        b = _bashrc_inside(p)
        if b and (not hint or hint in str(p).lower()):
            return p, b

    # 2) Disk scan with hint
    for cand in _candidate_install_dirs():
        b = _bashrc_inside(cand)
        if b and hint and hint in cand.name.lower():
            return cand, b

    # 3) Disk scan without hint
    for cand in _candidate_install_dirs():
        b = _bashrc_inside(cand)
        if b:
            return cand, b

    return None


def _source_bashrc(bashrc: Path) -> dict[str, str]:
    """Spawn `bash -c 'source <bashrc>; env -0'` and parse the resulting env.

    Returns the full environment dict that the OpenFOAM bashrc establishes.
    Raises RunnerError on failure.
    """
    bash = shutil.which("bash")
    if bash is None:
        raise RunnerError(
            "bash not found on PATH — OpenFOAM runner requires a POSIX shell",
            type="ShellMissing",
        )

    # `env -0` prints NUL-delimited NAME=VALUE pairs; safer than newlines
    # because OpenFOAM env vars sometimes contain newlines themselves.
    cmd = [bash, "--noprofile", "--norc", "-c", f"source {bashrc} >/dev/null 2>&1; env -0"]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=False,  # binary so NUL split works
        )
    except subprocess.CalledProcessError as e:
        raise RunnerError(
            f"sourcing {bashrc} failed (exit {e.returncode}): "
            f"{(e.stderr or b'').decode(errors='replace').strip()}",
            type="BashrcSourceFailure",
        ) from e
    except FileNotFoundError as e:
        raise RunnerError(f"bash not found: {e}", type="ShellMissing") from e

    out: dict[str, str] = {}
    for chunk in result.stdout.split(b"\x00"):
        if not chunk:
            continue
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            text = chunk.decode("utf-8", errors="replace")
        if "=" not in text:
            continue
        k, _, v = text.partition("=")
        out[k] = v

    if "WM_PROJECT_DIR" not in out:
        raise RunnerError(
            f"sourced {bashrc} but WM_PROJECT_DIR is still unset",
            type="BashrcSourceFailure",
        )
    return out


class OpenFOAMShellRunner(RunnerLoop):
    """SDK-less OpenFOAM runner. Subclassed only for profile_name binding."""

    profile_name = "<unset>"

    def __init__(self) -> None:
        super().__init__()
        self._install_dir: Path | None = None
        self._bashrc: Path | None = None
        self._foam_env: dict[str, str] | None = None
        self._session_id: str | None = None
        self._cwd: Path | None = None
        self._runs: list[dict] = []
        self._sdk_version: str = "n/a"  # OpenFOAM has no SDK
        self._solver_version: str = "?"

    # ── handshake ────────────────────────────────────────────────────────

    def op_handshake(self, args: dict) -> dict:
        # Locate the install but DO NOT source the bashrc here yet —
        # sourcing can be slow (a second or two) and we want handshake to
        # be cheap and crash-free even when the user just wants to inspect
        # the env via `sim env list` etc.
        found = _detect_install_for_profile(self.profile_name)
        if found is not None:
            self._install_dir, self._bashrc = found

        # Solver version: prefer WM_PROJECT_VERSION from the inherited env
        # (if the user already sourced bashrc in their shell), else fall
        # back to the hint encoded in the profile name.
        env_version = os.environ.get("WM_PROJECT_VERSION", "").strip()
        if env_version:
            self._solver_version = env_version
        elif self._install_dir is not None:
            # Try to derive from the install dir name (e.g. "openfoam-v2406")
            name = self._install_dir.name.lower()
            for tag in ("v2406", "v2312", "v2306", "v2206"):
                if tag in name:
                    self._solver_version = tag
                    break
            else:
                self._solver_version = name
        else:
            self._solver_version = _PROFILE_VERSION_HINTS.get(self.profile_name, "?")

        return {
            "sdk_version": self._sdk_version,
            "solver_version": self._solver_version,
            "profile": self.profile_name,
            "install_dir": str(self._install_dir) if self._install_dir else None,
            "bashrc": str(self._bashrc) if self._bashrc else None,
        }

    # ── connect / disconnect ────────────────────────────────────────────

    def op_connect(self, args: dict) -> dict:
        if self._foam_env is not None:
            raise RunnerError("session already active")

        if self._bashrc is None:
            raise RunnerError(
                f"no OpenFOAM install found for profile {self.profile_name!r}. "
                f"Set WM_PROJECT_DIR or install OpenFOAM under /opt/openfoam-v*",
                type="InstallMissing",
            )

        self._foam_env = _source_bashrc(self._bashrc)
        # Refresh solver version from the freshly-sourced env
        self._solver_version = self._foam_env.get(
            "WM_PROJECT_VERSION", self._solver_version
        )

        cwd = args.get("cwd")
        self._cwd = Path(cwd) if cwd else Path.cwd()
        self._session_id = str(uuid.uuid4())

        return {
            "session_id": self._session_id,
            "mode": "shell",
            "source": "bashrc",
            "profile": self.profile_name,
            "sdk_version": self._sdk_version,
            "solver_version": self._solver_version,
            "wm_project_dir": self._foam_env.get("WM_PROJECT_DIR"),
            "cwd": str(self._cwd),
        }

    def op_disconnect(self, args: dict) -> dict:
        if self._foam_env is None:
            return {"already_disconnected": True}
        sid = self._session_id
        self._foam_env = None
        self._session_id = None
        self._cwd = None
        return {"session_id": sid, "disconnected": True}

    # ── exec / inspect ──────────────────────────────────────────────────

    def op_exec(self, args: dict) -> dict:
        if self._foam_env is None:
            raise RunnerError("no active session — call op=connect first")

        code = args.get("code") or ""
        label = args.get("label") or "snippet"
        # Per-call cwd override (so an agent can `cd` into a tutorial dir
        # without polluting the runner's global state).
        cwd_override = args.get("cwd")
        cwd = Path(cwd_override) if cwd_override else (self._cwd or Path.cwd())

        # Strip the historical #!openfoam shebang if the caller still sends it.
        body = code
        if body.lstrip().startswith("#!openfoam"):
            body = body.split("\n", 1)[1] if "\n" in body else ""

        bash = shutil.which("bash")
        if bash is None:
            raise RunnerError("bash not found on PATH", type="ShellMissing")

        started = time.time()
        try:
            result = subprocess.run(
                [bash, "--noprofile", "--norc", "-c", body],
                env=self._foam_env,
                cwd=str(cwd),
                capture_output=True,
                text=True,
            )
            ok = result.returncode == 0
            stdout = result.stdout
            stderr = result.stderr
            error = None if ok else f"bash exited {result.returncode}"
        except Exception as e:  # pragma: no cover — unexpected
            ok = False
            stdout = ""
            stderr = ""
            error = f"{type(e).__name__}: {e}"
            result = None

        elapsed = round(time.time() - started, 4)
        record: dict[str, Any] = {
            "run_id": str(uuid.uuid4()),
            "session_id": self._session_id,
            "label": label,
            "ok": ok,
            "stdout": stdout,
            "stderr": stderr,
            "error": error,
            "result": None,
            "elapsed_s": elapsed,
            "exit_code": result.returncode if result is not None else None,
            "cwd": str(cwd),
        }
        self._runs.append(record)
        return record

    def op_inspect(self, args: dict) -> dict:
        name = args.get("name") or "session.summary"

        if name == "session.versions":
            return {
                "sdk": None,  # SDK-less driver
                "solver": {"name": "openfoam", "version": self._solver_version},
                "profile": self.profile_name,
            }
        if name == "session.summary":
            return {
                "session_id": self._session_id,
                "mode": "shell",
                "profile": self.profile_name,
                "run_count": len(self._runs),
                "connected": self._foam_env is not None,
                "wm_project_dir": (self._foam_env or {}).get("WM_PROJECT_DIR"),
                "cwd": str(self._cwd) if self._cwd else None,
            }
        if name == "last.result":
            if not self._runs:
                return {"has_last_run": False}
            return {"has_last_run": True, **self._runs[-1]}
        raise RunnerError(f"unknown inspect target: {name}", type="UnknownInspect")


# ── per-profile entry points ────────────────────────────────────────────────


def _make_main(profile: str):
    def main() -> int:
        runner = OpenFOAMShellRunner()
        runner.profile_name = profile
        return runner.run()
    return main


# Default entry point: profile is taken from $SIM_RUNNER_PROFILE so a single
# module can serve all openfoam_v* profiles. The spawn helper sets this var
# from the compatibility.yaml profile name.
def main() -> int:
    profile = os.environ.get("SIM_RUNNER_PROFILE", "openfoam_v2406")
    runner = OpenFOAMShellRunner()
    runner.profile_name = profile
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
