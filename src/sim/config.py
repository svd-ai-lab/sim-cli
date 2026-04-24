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
from typing import Any

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
