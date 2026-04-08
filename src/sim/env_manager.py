"""Per-profile virtual environment management.

Each compatibility profile (e.g. ``pyfluent_0_38_modern``) gets its own
isolated venv under ``$SIM_DIR/envs/<profile-name>/``. Inside that venv we
install the SDK pinned by the profile, plus sim-cli itself (so the runner
module under ``sim._runners.*`` is importable).

Backends:

* If the ``uv`` executable is on PATH we shell out to it (fast Rust impl).
* Otherwise we fall back to stdlib ``venv`` + ``pip`` (slower but works on any
  Python install — important for first-time users).

This module is pure Python; it does not import any solver SDK. It is safe to
call from the core ``sim`` process which must stay SDK-free per the
architecture in ``docs/architecture/version-compat.md``.

Public surface:

    sim_dir() -> Path                       # the root .sim/ directory
    envs_dir() -> Path                      # .sim/envs/
    env_path(profile_name) -> Path
    env_python(profile_name) -> Path
    env_state(profile_name) -> dict | None  # parsed sim-env.json or None
    install(profile_name, ...) -> dict      # create venv + install SDK + sim-cli
    list_envs() -> list[dict]
    remove(profile_name, force=False) -> bool
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from sim.compat import Profile, find_profile


# ── paths ──────────────────────────────────────────────────────────────────


def sim_dir() -> Path:
    """Root directory for sim's per-host state. Honors $SIM_DIR override."""
    raw = os.environ.get("SIM_DIR")
    if raw:
        return Path(raw)
    return Path.cwd() / ".sim"


def envs_dir() -> Path:
    return sim_dir() / "envs"


def env_path(profile_name: str) -> Path:
    return envs_dir() / profile_name


def env_python(profile_name: str) -> Path:
    """Filesystem path to the python.exe / python inside a profile env."""
    p = env_path(profile_name)
    if os.name == "nt":
        return p / "Scripts" / "python.exe"
    return p / "bin" / "python"


def _env_state_file(profile_name: str) -> Path:
    return env_path(profile_name) / "sim-env.json"


def env_state(profile_name: str) -> dict | None:
    f = _env_state_file(profile_name)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── backend selection ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Backend:
    kind: str         # "uv" or "stdlib"
    create_venv: tuple[str, ...]    # argv prefix that creates a venv at the given path
    install_into: tuple[str, ...]   # argv prefix that installs packages into a venv


def _detect_backend() -> _Backend:
    """Prefer uv when available, fall back to stdlib venv + pip."""
    uv = shutil.which("uv")
    if uv:
        return _Backend(
            kind="uv",
            create_venv=(uv, "venv", "--python", sys.executable),
            install_into=(uv, "pip", "install"),
        )
    return _Backend(
        kind="stdlib",
        create_venv=(sys.executable, "-m", "venv"),
        install_into=("",),  # placeholder; resolved per env
    )


# ── core operations ────────────────────────────────────────────────────────


def install(
    profile_name: str,
    *,
    upgrade: bool = False,
    quiet: bool = False,
    extra_packages: tuple[str, ...] = (),
) -> dict:
    """Create / refresh the venv for one profile and install the SDK + sim-cli.

    Args:
        profile_name: e.g. "pyfluent_0_38_modern". Must exist in some
            driver's compatibility.yaml.
        upgrade: if True, reinstall even if the env already exists.
        quiet: suppress subprocess output.
        extra_packages: additional packages to install (used by tests).

    Returns:
        A dict describing the resulting env state (same shape as
        ``env_state(profile_name)``).

    Raises:
        ValueError if the profile is unknown.
        RuntimeError if subprocess invocation fails.
    """
    found = find_profile(profile_name)
    if not found:
        raise ValueError(
            f"unknown profile: {profile_name!r}. "
            f"Run `sim env list --catalogue` to see available profiles."
        )
    driver_name, profile = found

    if profile.is_metadata_only:
        raise ValueError(
            f"profile {profile_name!r} is metadata-only (no SDK to install, "
            f"no runner subprocess). The driver lives entirely in its "
            f"PATH-installed binaries — `sim env install` is a no-op for it. "
            f"Use `sim check {driver_name}` to verify the binary install instead."
        )

    target = env_path(profile_name)
    state_file = _env_state_file(profile_name)

    if target.exists() and not upgrade:
        if state_file.is_file():
            # Already bootstrapped — return current state.
            return env_state(profile_name) or {"profile": profile_name, "status": "exists"}
        # Directory exists but no state file → broken/stale, scrub it.
        shutil.rmtree(target)

    if upgrade and target.exists():
        shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)

    backend = _detect_backend()
    started = time.time()

    # 1) Create the venv
    create_argv = list(backend.create_venv) + [str(target)]
    _run_subprocess(create_argv, quiet=quiet, step="create venv")

    py = env_python(profile_name)
    if not py.is_file():
        raise RuntimeError(f"venv created but python not found at {py}")

    # 2) Build the install argv (uv vs stdlib pip)
    if backend.kind == "uv":
        # uv pip install --python <env-python> <packages...>
        install_argv: list[str] = list(backend.install_into) + ["--python", str(py)]
    else:
        # <env-python> -m pip install <packages...>
        install_argv = [str(py), "-m", "pip", "install", "--upgrade", "pip"]
        _run_subprocess(install_argv, quiet=quiet, step="upgrade pip")
        install_argv = [str(py), "-m", "pip", "install"]

    # 3) Install the SDK pinned by the profile (if any).
    # SDK-less drivers (e.g. OpenFOAM — the solver IS its own scripting env)
    # leave profile.sdk as None and we skip the SDK install entirely.
    if profile.sdk is not None:
        sdk_spec = _spec_to_pip_arg(profile.sdk)
        sdk_pkg = _sdk_package_for_profile(driver_name, profile)
        sdk_arg: str | None = f"{sdk_pkg}{sdk_spec}"
    else:
        sdk_pkg = None
        sdk_arg = None

    # 4) Install sim-cli into the env so the runner module is importable.
    # We install from the local checkout in editable mode if running from a
    # source tree; otherwise we install the same version published wherever
    # this sim-cli came from. For M1 the source-tree path is the one that
    # matters (every dev runs out of a checkout).
    #
    # Editable install matters: a runner module added to the checkout AFTER
    # the env was bootstrapped should still be importable next session
    # without `sim env install --upgrade`. Editable mode achieves that by
    # putting the checkout's site-packages directly on the env's sys.path.
    sim_source = _resolve_sim_source()
    sim_pkgs: list[str]
    if Path(sim_source).is_dir():
        sim_pkgs = ["-e", sim_source]
    else:
        sim_pkgs = [sim_source]

    # Install SDK in one call, sim-cli (editable) in a separate call so an
    # SDK install failure doesn't take sim-cli down with it. SDK-less drivers
    # skip the first call entirely.
    if sdk_arg is not None:
        _run_subprocess(install_argv + [sdk_arg, *extra_packages], quiet=quiet, step="install SDK")
    elif extra_packages:
        _run_subprocess(install_argv + list(extra_packages), quiet=quiet, step="install extras")
    _run_subprocess(install_argv + sim_pkgs, quiet=quiet, step="install sim-cli (editable)")

    elapsed = round(time.time() - started, 2)

    state = {
        "profile": profile_name,
        "driver": driver_name,
        "sdk_package": sdk_pkg,
        "sdk_spec": profile.sdk,
        "runner_module": profile.runner_module,
        "skill_revision": profile.skill_revision,
        "env_path": str(target),
        "python": str(py),
        "backend": backend.kind,
        "installed_at": time.time(),
        "install_seconds": elapsed,
        "status": "ready",
    }
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def list_envs() -> list[dict]:
    """Enumerate every profile env that has been bootstrapped on this host."""
    root = envs_dir()
    if not root.is_dir():
        return []
    out: list[dict] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        st = env_state(child.name)
        if st:
            out.append(st)
        else:
            out.append({
                "profile": child.name,
                "env_path": str(child),
                "status": "broken",  # missing sim-env.json
            })
    return out


def remove(profile_name: str, *, force: bool = False) -> bool:
    """Tear down a profile env. Returns True on success."""
    target = env_path(profile_name)
    if not target.exists():
        if force:
            return True
        return False
    shutil.rmtree(target)
    return True


# ── helpers ────────────────────────────────────────────────────────────────


def _spec_to_pip_arg(spec: str) -> str:
    """Convert a PEP 440 specifier into pip-compatible form.

    The schema stores ``">=0.38,<0.39"`` which pip already accepts directly;
    this helper exists so we can bend it later if a vendor needs special
    treatment (e.g. extra index URLs).
    """
    return spec


def _sdk_package_for_profile(driver_name: str, profile: Profile) -> str | None:
    """Resolve the PyPI distribution name for a given profile.

    For now we look it up via the driver's full compatibility.yaml; in the
    future we may want to override per-profile (e.g. matlabengine has wheels
    keyed by MATLAB release).
    """
    from sim.compat import load_compatibility

    driver_dir = Path(__file__).parent / "drivers" / driver_name
    compat = load_compatibility(driver_dir)
    return compat.sdk_package


def _resolve_sim_source() -> str:
    """Pick the right sim-cli source spec to install into a profile env.

    Strategy:
      1. If we live inside an editable checkout (we can see pyproject.toml
         next to a `src/sim/` package), install from that path.
      2. Otherwise install `sim-cli` from PyPI by name (will work once we
         publish; for M1 this branch is exercised by CI only).
    """
    here = Path(__file__).resolve()
    # .../src/sim/env_manager.py -> walk up to find pyproject.toml
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "sim").is_dir():
            return str(parent)
    return "sim-cli"


def _run_subprocess(argv: list[str], *, quiet: bool, step: str) -> None:
    if not quiet:
        printable = " ".join(repr(a) if " " in a else a for a in argv)
        print(f"  [{step}] {printable}", flush=True)
    try:
        result = subprocess.run(
            argv,
            check=True,
            stdout=subprocess.PIPE if quiet else None,
            stderr=subprocess.PIPE if quiet else None,
            text=True,
        )
        if quiet:
            return
        if result.stdout:
            pass  # already streamed
    except subprocess.CalledProcessError as e:
        msg = f"step '{step}' failed (exit {e.returncode})"
        if e.stderr:
            msg += f"\n    stderr: {e.stderr.strip()}"
        raise RuntimeError(msg) from e
