"""CLI manifest emitter for ``sim describe``.

Agents call ``sim describe --json`` once at session start to learn the entire
CLI surface: every command, every flag, every example, every error code,
every output schema. They then route subsequent calls from that manifest
without grepping ``--help`` or guessing.

The manifest schema is versioned (``schema_version``); breaking changes
bump the version. Additive changes are free.

The manifest is built by introspecting the click app — what's there at
runtime is what's described, so commands can never silently fall out of
sync with their documentation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import click


SCHEMA_VERSION = 1


# ── Examples registry ───────────────────────────────────────────────────────
#
# Each command's example invocations live here. The describe command merges
# this with the click introspection. Keep examples short and realistic —
# agents copy them.

_EXAMPLES: dict[str, list[dict[str, str]]] = {
    "serve": [
        {"cmd": "sim serve", "summary": "Start the HTTP server on the default port."},
        {"cmd": "sim serve --host 0.0.0.0 --port 7600 --reload",
         "summary": "Bind to all interfaces with auto-reload (dev mode)."},
    ],
    "check": [
        {"cmd": "sim check --all", "summary": "Detect every installed solver."},
        {"cmd": "sim check coolprop --json", "summary": "Detect one driver, JSON output."},
    ],
    "lint": [
        {"cmd": "sim lint script.py --solver gmsh",
         "summary": "Validate a script before running it."},
    ],
    "run": [
        {"cmd": "sim run script.py --solver gmsh",
         "summary": "Execute a script via the chosen driver."},
        {"cmd": "sim run script.py --solver gmsh --json",
         "summary": "Same, but emit RunResult as JSON for an agent."},
    ],
    "connect": [
        {"cmd": "sim connect --solver gmsh",
         "summary": "Start a persistent solver session."},
    ],
    "exec": [
        {"cmd": 'sim exec "x = 2 + 2; print(x)"',
         "summary": "Run a snippet in the active session."},
        {"cmd": "sim exec --file snippet.py",
         "summary": "Run a file's contents in the active session."},
    ],
    "inspect": [
        {"cmd": "sim inspect session.summary",
         "summary": "Print a summary of the active session's state."},
    ],
    "ps": [
        {"cmd": "sim ps", "summary": "List active sessions."},
        {"cmd": "sim ps --json", "summary": "Same, machine-readable."},
    ],
    "disconnect": [
        {"cmd": "sim disconnect", "summary": "Tear down the active session."},
        {"cmd": "sim disconnect --stop-server", "summary": "Also stop sim-server."},
    ],
    "stop": [
        {"cmd": "sim stop", "summary": "Stop the sim-server process."},
    ],
    "screenshot": [
        {"cmd": "sim screenshot -o desktop.png",
         "summary": "Capture the server's desktop to a PNG file."},
    ],
    "logs": [
        {"cmd": "sim logs --limit 20", "summary": "Show the last 20 history entries."},
    ],
    "config show": [
        {"cmd": "sim config show --json",
         "summary": "Print the resolved config (project + global merged)."},
    ],
    "config init": [
        {"cmd": "sim config init project",
         "summary": "Create a starter .sim/config.toml in the current project."},
    ],
    "config path": [
        {"cmd": "sim config path --json",
         "summary": "Print the location of the global and project config files."},
    ],
    "describe": [
        {"cmd": "sim describe --json",
         "summary": "Emit the full CLI manifest. Run this once at session start."},
        {"cmd": "sim describe run --json",
         "summary": "Manifest entry for one command."},
        {"cmd": "sim describe --error-codes",
         "summary": "List the closed enum of error codes."},
    ],
}


# ── Error codes (closed enum) ───────────────────────────────────────────────
#
# Mirror of docs/agent-readability.md §1 — the source of truth for code
# strings agents pattern-match. Adding a new code requires updating both
# this dict and the doc.

ERROR_CODES: dict[str, str] = {
    "SOLVER_NOT_INSTALLED":
        "The named driver loaded but the underlying solver is not detected on this host.",
    "SOLVER_NOT_DETECTED_FOR_SCRIPT":
        "A script was given without --solver and no driver claimed it.",
    "LINT_FAILED":
        "sim lint produced at least one error-level diagnostic.",
    "RUN_FAILED":
        "The solver returned non-zero or the driver detected an error in the output.",
    "SESSION_NOT_FOUND":
        "--session <id> does not match any active session on the server.",
    "PLUGIN_NOT_FOUND":
        "sim plugin could not resolve a plugin name (not in the index, no local file).",
    "PLUGIN_INSTALL_FAILED":
        "pip install for a plugin returned non-zero.",
    "PROTOCOL_VIOLATION":
        "A driver returned a value that doesn't match DriverProtocol.",
    "NONINTERACTIVE_INPUT_REQUIRED":
        "--no-interactive is set and the command would otherwise prompt.",
}


# ── Schema descriptions ─────────────────────────────────────────────────────
#
# These mirror the dataclasses in sim.driver. We don't ship full JSON Schema
# yet (drives complexity for marginal value); a structured description
# suffices for agents to know "this dict has these keys".

SCHEMAS: dict[str, dict[str, Any]] = {
    "RunResult": {
        "type": "object",
        "description": "Result of one solver script execution.",
        "properties": {
            "ok": {"type": "boolean", "description": "exit_code == 0 AND no errors."},
            "exit_code": {"type": "integer"},
            "stdout": {"type": "string"},
            "stderr": {"type": "string"},
            "errors": {"type": "array", "items": {"type": "string"}},
            "duration_s": {"type": "number"},
            "script": {"type": "string"},
            "solver": {"type": "string"},
            "timestamp": {"type": "string", "format": "date-time"},
            "diagnostics": {"type": "array",
                            "items": {"type": "object",
                                      "properties": {"level": {"type": "string"},
                                                     "message": {"type": "string"},
                                                     "line": {"type": ["integer", "null"]}}}},
            "artifacts": {"type": "array", "items": {"type": "object"}},
            "workspace_delta": {
                "type": "array",
                "description": "Files added/modified under cwd during the run.",
                "items": {"type": "object",
                          "properties": {"path": {"type": "string"},
                                         "kind": {"enum": ["added", "modified"]},
                                         "size": {"type": "integer"}}}},
        },
    },
    "LintResult": {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "diagnostics": {"type": "array",
                            "items": {"type": "object",
                                      "properties": {"level": {"enum": ["error", "warning", "info"]},
                                                     "message": {"type": "string"},
                                                     "line": {"type": ["integer", "null"]}}}},
        },
    },
    "ConnectionInfo": {
        "type": "object",
        "properties": {
            "solver": {"type": "string"},
            "version": {"type": ["string", "null"]},
            "status": {"enum": ["ok", "not_installed", "error"]},
            "message": {"type": "string"},
            "solver_version": {"type": ["string", "null"]},
        },
    },
    "ErrorEnvelope": {
        "type": "object",
        "description": "Returned by every command on failure when --json is set.",
        "properties": {
            "ok": {"const": False},
            "error_code": {"enum": list(ERROR_CODES.keys())},
            "message": {"type": "string", "maxLength": 280},
            "details": {"type": "object"},
        },
    },
    "PluginInfo": {
        "type": "object",
        "description": "Lightweight metadata exposed by every plugin via the sim.plugins entry-point group.",
        "properties": {
            "name": {"type": "string"},
            "summary": {"type": "string"},
            "homepage": {"type": "string"},
            "license_class": {"enum": ["oss", "commercial"]},
            "solver_name": {"type": "string"},
        },
    },
}


# ── Introspection ───────────────────────────────────────────────────────────


def _describe_param(param: click.Parameter) -> dict[str, Any]:
    """Render one click parameter (option/argument) as a manifest entry."""
    kind = "argument" if isinstance(param, click.Argument) else "option"
    out: dict[str, Any] = {
        "kind": kind,
        "name": param.name,
        "required": bool(param.required),
        "multiple": bool(getattr(param, "multiple", False)),
        "is_flag": bool(getattr(param, "is_flag", False)),
    }
    if isinstance(param, click.Option):
        out["flags"] = list(param.opts) + list(param.secondary_opts or [])
        if param.default is not None and not getattr(param, "is_flag", False):
            try:
                out["default"] = param.default if isinstance(
                    param.default, (str, int, float, bool, type(None))
                ) else repr(param.default)
            except Exception:  # noqa: BLE001 — defensive against weird default reprs
                out["default"] = None
    help_text = getattr(param, "help", None)
    if help_text:
        out["help"] = help_text
    return out


def _describe_command(name: str, cmd: click.Command) -> dict[str, Any]:
    """Render one click command as a manifest entry.

    Example lookup is normalized so callers can pass either the canonical
    space-separated form (``"config show"``) or the dotted form
    (``"config.show"``).
    """
    canonical = name.replace(".", " ")
    entry: dict[str, Any] = {
        "name": name,
        "summary": (cmd.short_help or (cmd.help or "").splitlines()[0:1] or [""])[0],
        "help": cmd.help or "",
        "params": [_describe_param(p) for p in cmd.params],
        "examples": _EXAMPLES.get(canonical, []),
    }
    return entry


def _walk(group: click.Group, prefix: str = "") -> list[dict[str, Any]]:
    """Walk a click group, yielding manifest entries for every command.

    Nested groups produce dotted names (``"config show"``).
    """
    entries: list[dict[str, Any]] = []
    for sub_name, sub_cmd in sorted(group.commands.items()):
        full = f"{prefix}{sub_name}" if prefix else sub_name
        if isinstance(sub_cmd, click.Group):
            # Describe the group itself plus walk into it.
            entries.append(_describe_command(full, sub_cmd))
            entries.extend(_walk(sub_cmd, prefix=f"{full} "))
        else:
            entries.append(_describe_command(full, sub_cmd))
    return entries


def build_manifest(app: click.Group, version: str) -> dict[str, Any]:
    """Top-level: build the full manifest for an app."""
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "commands": _walk(app),
        "schemas": SCHEMAS,
        "error_codes": [
            {"code": code, "description": desc}
            for code, desc in ERROR_CODES.items()
        ],
    }


def build_command_entry(app: click.Group, command_path: str) -> dict[str, Any] | None:
    """Resolve a (possibly dotted/space-separated) command path to one entry."""
    parts = command_path.replace(".", " ").split()
    cur: click.Command | click.Group = app
    for part in parts:
        if not isinstance(cur, click.Group) or part not in cur.commands:
            return None
        cur = cur.commands[part]
    return _describe_command(command_path, cur)
