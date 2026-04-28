"""Two-tier config: global ~/.sim/config.toml + project .sim/config.toml.

Resolution order for any lookup:
  env var  >  project .sim/config.toml  >  global ~/.sim/config.toml  >  default

Usage:
    from sim import config
    port    = config.resolve_server_port()
    path    = config.resolve_solver_path("fluent")
    history = config.history_path()

With no config files present, behavior is identical to pre-#5 (env var
and auto-detection only). Missing or malformed TOML falls back silently.

See docs/architecture/multi-session-and-config.md for the schema rules.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any  # noqa: F401 — used in newer additions below

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — exercised only on 3.10
    import tomli as tomllib


DEFAULT_SERVER_PORT = 7600
DEFAULT_SERVER_HOST = "127.0.0.1"


# ── Paths ────────────────────────────────────────────────────────────────────


def sim_home() -> Path:
    """Global `~/.sim/` dir. Override with SIM_HOME env var (test isolation)."""
    raw = os.environ.get("SIM_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".sim"


def project_sim_dir() -> Path:
    """Project-level `.sim/` dir. Override with SIM_DIR env var (back-compat)."""
    raw = os.environ.get("SIM_DIR")
    if raw:
        return Path(raw)
    return Path.cwd() / ".sim"


def global_config_path() -> Path:
    return sim_home() / "config.toml"


def project_config_path() -> Path:
    return project_sim_dir() / "config.toml"


def history_path() -> Path:
    return sim_home() / "history.jsonl"


def server_log_path() -> Path:
    """Server log file lives under the project `.sim/` so each project gets its own."""
    return project_sim_dir() / "sim-serve.log"


# ── Loading ──────────────────────────────────────────────────────────────────


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Return a new dict: overlay wins on scalar keys, sub-dicts merge recursively."""
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    """Merge global + project configs (project wins). Returns `{}` when both absent."""
    g = _read_toml(global_config_path())
    p = _read_toml(project_config_path())
    return _deep_merge(g, p)


# The merged config is read many times per CLI invocation; cache it for
# the duration of the process. Tests that mutate config files between
# calls should invoke `clear_cache()`.

_cached: dict[str, Any] | None = None


def _cached_config() -> dict[str, Any]:
    global _cached
    if _cached is None:
        _cached = load_config()
    return _cached


def clear_cache() -> None:
    """Invalidate the cached merged config. Tests only."""
    global _cached
    _cached = None


# ── Resolvers ────────────────────────────────────────────────────────────────


def resolve_server_port() -> int:
    """env SIM_PORT > config [server].port > default 7600."""
    raw = os.environ.get("SIM_PORT")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    cfg = _cached_config()
    port = cfg.get("server", {}).get("port")
    if isinstance(port, int):
        return port
    return DEFAULT_SERVER_PORT


def resolve_server_host() -> str:
    """env SIM_HOST > config [server].host > default 127.0.0.1."""
    raw = os.environ.get("SIM_HOST")
    if raw:
        return raw
    cfg = _cached_config()
    host = cfg.get("server", {}).get("host")
    if isinstance(host, str) and host:
        return host
    return DEFAULT_SERVER_HOST


def resolve_solver_path(solver: str) -> str | None:
    """Look up a solver's install path override.

    Lookup order: env var (driver-specific) > config [solvers.<name>].path > None.

    The env var name is driver-specific (AWP_ROOT252, FLUENT_ROOT, ...).
    We only consult the config tier here — env vars are read inside each
    driver's `detect_installed()` as before, so installations without any
    config file work unchanged.
    """
    cfg = _cached_config()
    return cfg.get("solvers", {}).get(solver, {}).get("path")


def resolve_solver_profile(solver: str) -> str | None:
    """Project pin for a solver profile (e.g. pyfluent_0_37_legacy).

    Advisory only under multi-session (see design note §4): if the
    `sim connect` call names a different solver, this pin is ignored with
    a warning. Same-solver mismatches are caller-decided.
    """
    cfg = _cached_config()
    return cfg.get("solvers", {}).get(solver, {}).get("profile")


def list_solver_pins() -> dict[str, dict]:
    """All `[solvers.<name>]` tables from the merged config."""
    cfg = _cached_config()
    solvers = cfg.get("solvers", {})
    return {k: v for k, v in solvers.items() if isinstance(v, dict)}


# ── Init helper ──────────────────────────────────────────────────────────────


GLOBAL_STUB = """\
# ~/.sim/config.toml — global sim-cli settings
#
# Uncomment and edit values you want to override. With this file absent
# or empty, sim-cli behaves exactly as it did before (env vars +
# auto-detection only).

# [server]
# port = 7600
# host = "127.0.0.1"

# [solvers.fluent]
# path = "C:\\\\Program Files\\\\ANSYS Inc\\\\v252"

# [solvers.mapdl]
# path = "C:\\\\Program Files\\\\ANSYS Inc\\\\v252"
"""

PROJECT_STUB = """\
# .sim/config.toml — project-level sim-cli settings
#
# Overrides ~/.sim/config.toml; env vars override this.

# [server]
# port = 7600

# [solvers.fluent]
# profile = "pyfluent_0_38_modern"
"""


def init_config_file(scope: str) -> Path:
    """Create a stub config file at the given scope if it does not exist.

    `scope` is 'global' or 'project'. Returns the path of the written (or
    already-existing) file. Directories are created as needed.
    """
    if scope == "global":
        path = global_config_path()
        content = GLOBAL_STUB
    elif scope == "project":
        path = project_config_path()
        content = PROJECT_STUB
    else:
        raise ValueError(f"scope must be 'global' or 'project', got {scope!r}")

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")
    return path


# ── sim.toml — project manifest (plugins, defaults) ─────────────────────────
#
# Distinct from the global/project `config.toml` files above: `sim.toml`
# lives at the project root and declares plugins to install + project-wide
# defaults. It's the file `sim init` creates and `sim setup` reads. Two
# files because the `[server] / [solvers.<x>]` config tier predates the
# plugin layer and we don't want to break existing workflows by merging.

SIM_TOML_NAME = "sim.toml"


def project_sim_toml_path() -> Path:
    """Walk up from cwd looking for sim.toml; return the canonical location.

    Returns the cwd path when no sim.toml is found, so `sim init` writes
    there. Walk-up is for the `sim setup` and `sim config show` cases.
    """
    cur = Path.cwd().resolve()
    for parent in (cur, *cur.parents):
        candidate = parent / SIM_TOML_NAME
        if candidate.is_file():
            return candidate
    return cur / SIM_TOML_NAME


SIM_TOML_STUB = """\
# sim.toml — project manifest for sim-cli
#
# Declare the plugins your project depends on and any project-wide defaults.
# `sim setup` reads this file; `sim config show --json` prints the merged
# resolved config.

[sim]
# default_solver = "gmsh"
# workspace = "./workspace"

# Each entry under [[sim.plugins]] declares one plugin to install.
# Sources accepted: name (resolved via the public index), git+https://...,
# wheel = "./path/to/file.whl", or version = "==X.Y.Z" / ">=X".
#
# [[sim.plugins]]
# name = "coolprop"
# version = ">=0.1.0"
"""


def init_sim_toml(*, force: bool = False) -> Path:
    """Create a starter sim.toml in the cwd. Idempotent unless ``force=True``."""
    path = Path.cwd() / SIM_TOML_NAME
    if path.exists() and not force:
        return path
    path.write_text(SIM_TOML_STUB, encoding="utf-8")
    return path


def load_sim_toml() -> dict[str, Any]:
    """Load the project's sim.toml, walking up from cwd. Returns {} if none."""
    path = project_sim_toml_path()
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return {}


def validate_sim_toml(path: Path) -> list[str]:
    """Return a list of human-readable validation errors. Empty == valid.

    Schema (informal):
        [sim]
        default_solver = <string>?
        workspace      = <string>?
        server_port    = <int>?

        [[sim.plugins]]
        name    = <string>           # required
        version = <string>?
        git     = <string>?
        wheel   = <string>?          # local path
    """
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"file not found: {path}")
        return errors
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        errors.append(f"invalid TOML: {e}")
        return errors

    sim = data.get("sim")
    if sim is None:
        errors.append("missing [sim] table")
        return errors
    if not isinstance(sim, dict):
        errors.append("[sim] must be a table")
        return errors

    if "default_solver" in sim and not isinstance(sim["default_solver"], str):
        errors.append("[sim].default_solver must be a string")
    if "workspace" in sim and not isinstance(sim["workspace"], str):
        errors.append("[sim].workspace must be a string")
    if "server_port" in sim and not isinstance(sim["server_port"], int):
        errors.append("[sim].server_port must be an integer")

    plugins = sim.get("plugins") or []
    if not isinstance(plugins, list):
        errors.append("[[sim.plugins]] must be an array of tables")
    else:
        for i, p in enumerate(plugins):
            if not isinstance(p, dict):
                errors.append(f"[[sim.plugins]] entry #{i} must be a table")
                continue
            if "name" not in p or not isinstance(p["name"], str):
                errors.append(f"[[sim.plugins]] entry #{i} missing required 'name'")
                continue
            for k in ("version", "git", "wheel"):
                if k in p and not isinstance(p[k], str):
                    errors.append(f"[[sim.plugins]] {p['name']!r} field {k!r} must be a string")

    return errors


def derive_install_source(plugin_entry: dict[str, Any]) -> str:
    """Translate one [[sim.plugins]] entry to an install-source string.

    Resolution priority: explicit ``wheel`` path > explicit ``git`` URL
    > ``name@version`` if version set > bare ``name``.
    """
    if "wheel" in plugin_entry:
        return plugin_entry["wheel"]
    if "git" in plugin_entry:
        return f"git+{plugin_entry['git']}"
    name = plugin_entry["name"]
    version = plugin_entry.get("version")
    if version:
        # Strip leading == / >= so it composes with our @ form.
        v = version.lstrip(">=<! ")
        if version.startswith("=="):
            return f"{name}@{v}"
        # Range constraints: fall back to bare name and let pip resolve.
        return name
    return name
