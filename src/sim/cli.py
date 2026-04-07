"""sim CLI — unified interface for LLM agents to control CAD/CAE simulation software."""
from __future__ import annotations

import json as json_mod
import os
import sys
from pathlib import Path

import click

from sim import __version__
from sim.driver import RunResult
from sim.drivers import get_driver
from sim.runner import execute_script
from sim.store import RunStore


def _get_store() -> RunStore:
    root = os.environ.get("SIM_DIR", str(Path.cwd() / ".sim"))
    return RunStore(Path(root))


# ── Top-level group ──────────────────────────────────────────────────────────

@click.group()
@click.version_option(version=__version__)
@click.option("--json", "output_json", is_flag=True, help="JSON output for all commands.")
@click.option("--host", envvar="SIM_HOST", default=None,
              help="Remote sim-server host (e.g. 100.90.110.79). Default: localhost (auto-start).")
@click.option("--port", envvar="SIM_PORT", default=7600, type=int,
              help="sim-server port (default: 7600).")
@click.pass_context
def main(ctx, output_json, host, port):
    """sim — unified CLI for LLM agents to control CAD/CAE simulation software."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = output_json
    ctx.obj["host"] = host or "localhost"
    ctx.obj["port"] = port


# ── serve ────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--host", "serve_host", default="127.0.0.1",
              help="Bind address. Use 0.0.0.0 for Tailscale/network access.")
@click.option("--port", "serve_port", default=7600, type=int)
def serve(serve_host, serve_port):
    """Start the sim HTTP server (like ollama serve)."""
    import uvicorn
    from sim.server import app

    click.echo(f"[sim] server starting on {serve_host}:{serve_port}")
    if serve_host == "0.0.0.0":
        click.echo("[sim] accessible on network (Tailscale)")
    uvicorn.run(app, host=serve_host, port=serve_port, log_level="info")


# ── check ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("solver")
@click.pass_context
def check(ctx, solver):
    """Check solver availability and report version."""
    driver = get_driver(solver)
    if driver is None:
        click.echo(f"[sim] error: no driver for '{solver}'", err=True)
        sys.exit(1)

    info = driver.connect()
    if ctx.obj["json"]:
        click.echo(json_mod.dumps(info.to_dict(), indent=2))
    else:
        if info.status == "ok":
            click.echo(f"[sim] check: {info.message}")
        else:
            click.echo(f"[sim] check: {info.message}", err=True)
            sys.exit(1)


# ── lint ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("script", type=click.Path(exists=True))
@click.pass_context
def lint(ctx, script):
    """Validate a simulation script before execution."""
    script_path = Path(script)
    from sim.drivers import DRIVERS

    driver = None
    for d in DRIVERS:
        if d.detect(script_path):
            driver = d
            break
    if driver is None:
        from sim.drivers.pybamm import PyBaMMLDriver
        driver = PyBaMMLDriver()

    result = driver.lint(script_path)
    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result.to_dict(), indent=2))
    else:
        for d in result.diagnostics:
            symbol = "✓" if d.level == "info" else "⚠" if d.level == "warning" else "✗"
            loc = f" (line {d.line})" if d.line else ""
            click.echo(f"  {symbol} {d.message}{loc}")
        click.echo(f"[sim] lint: {'passed' if result.ok else 'failed'}")
    sys.exit(0 if result.ok else 1)


# ── run (one-shot script) ───────────────────────────────────────────────────

@main.command()
@click.argument("script", type=click.Path(exists=True))
@click.option("--solver", required=True, help="Solver to execute against.")
@click.pass_context
def run(ctx, script, solver):
    """Execute a simulation script in a subprocess (one-shot)."""
    driver = get_driver(solver)
    if driver is None:
        click.echo(f"[sim] error: no driver for '{solver}'", err=True)
        sys.exit(1)

    result = execute_script(Path(script), solver=solver, driver=driver)

    parsed = {}
    parsed = driver.parse_output(result.stdout)

    store = _get_store()
    run_id = store.save(result, parsed_output=parsed)

    if ctx.obj["json"]:
        data = result.to_dict()
        data["id"] = run_id
        data["parsed_output"] = parsed
        click.echo(json_mod.dumps(data, indent=2))
    else:
        status = "converged" if result.exit_code == 0 else "failed"
        click.echo(f"[sim] run:    {script} via {solver}")
        click.echo(f"[sim] status: {status} ({result.duration_s}s)")
        click.echo(f"[sim] log:    saved as #{run_id}")
        if result.exit_code != 0 and result.stderr:
            click.echo(f"[sim] stderr: {result.stderr}")
    sys.exit(result.exit_code)


# ── connect (persistent session) ────────────────────────────────────────────

@main.command()
@click.option("--solver", required=True, help="Solver name (e.g. pyfluent).")
@click.option("--mode", default="meshing", type=click.Choice(["meshing", "solver"]))
@click.option("--ui-mode", default="no_gui", type=click.Choice(["no_gui", "gui"]))
@click.option("--processors", default=1, type=int)
@click.pass_context
def connect(ctx, solver, mode, ui_mode, processors):
    """Launch a solver and hold a persistent session."""
    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    result = client.connect(solver=solver, mode=mode, ui_mode=ui_mode, processors=processors)

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        if result.get("ok"):
            click.echo("[sim] connect: session ready")
            if result.get("data"):
                click.echo(json_mod.dumps(result["data"], indent=4, default=str))
        else:
            click.echo(f"[sim] connect: failed — {result.get('error', 'unknown')}", err=True)
            sys.exit(1)


# ── exec (snippet in live session) ──────────────────────────────────────────

@main.command(name="exec")
@click.argument("code", required=False)
@click.option("--file", "code_file", type=click.Path(exists=True), help="Read code from file.")
@click.option("--label", default="cli-snippet", help="Label for this execution.")
@click.pass_context
def exec_cmd(ctx, code, code_file, label):
    """Execute a code snippet in the live session."""
    if code_file:
        code = Path(code_file).read_text(encoding="utf-8")
    if not code:
        click.echo("[sim] error: provide code as argument or via --file", err=True)
        sys.exit(1)

    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    result = client.run(code=code, label=label)

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        data = result.get("data", {})
        ok = data.get("ok", False)
        status = "OK" if ok else "FAIL"
        click.echo(f"  [{status}] label={label!r}  elapsed={data.get('elapsed_s', 0)}s")
        if data.get("stdout"):
            for line in data["stdout"].rstrip().splitlines():
                click.echo(f"  stdout: {line}")
        if data.get("stderr"):
            for line in data["stderr"].rstrip().splitlines():
                click.echo(f"  stderr: {line}")
        if data.get("error"):
            click.echo(f"  error: {data['error']}")
        if data.get("result") is not None:
            click.echo(f"  result: {data['result']}")
        if not ok:
            sys.exit(2)


# ── inspect (live session state) ─────────────────────────────────────────────

@main.command()
@click.argument("name", default="session.summary",
                type=click.Choice(["session.summary", "session.mode", "last.result", "workflow.summary"]))
@click.pass_context
def inspect(ctx, name):
    """Query live session state."""
    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    result = client.query(name=name)

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        if result.get("ok"):
            click.echo(json_mod.dumps(result["data"], indent=2, default=str))
        else:
            click.echo(f"[sim] error: {result.get('error')}", err=True)
            sys.exit(1)


# ── ps (list active sessions) ───────────────────────────────────────────────

@main.command()
@click.pass_context
def ps(ctx):
    """List active sessions."""
    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    result = client.status()

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        if result.get("connected"):
            click.echo(json_mod.dumps(result, indent=2, default=str))
        else:
            click.echo("[sim] no active session")


# ── disconnect ───────────────────────────────────────────────────────────────

@main.command()
@click.pass_context
def disconnect(ctx):
    """Tear down the active session."""
    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    result = client.disconnect()

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        if result.get("ok"):
            sid = result.get("data", {}).get("session_id", "?")
            click.echo(f"[sim] disconnected (session_id={sid})")
        else:
            click.echo(f"[sim] error: {result.get('error')}", err=True)
            sys.exit(1)


# ── screenshot ───────────────────────────────────────────────────────────────

@main.command()
@click.option("-o", "--output", default="screenshot.png", help="Output file path.")
@click.pass_context
def screenshot(ctx, output):
    """Capture the server desktop and save as PNG."""
    import base64
    from pathlib import Path

    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    result = client.screenshot()

    if not result.get("ok"):
        click.echo(f"[sim] error: {result.get('error')}", err=True)
        sys.exit(1)

    png_bytes = base64.b64decode(result["data"]["base64"])
    out_path = Path(output)
    out_path.write_bytes(png_bytes)
    w, h = result["data"]["width"], result["data"]["height"]
    click.echo(f"[sim] screenshot saved: {out_path} ({w}x{h})")


# ── logs (run history) ───────────────────────────────────────────────────────

@main.command()
@click.argument("target", required=False)
@click.option("--field", help="Extract a specific field from run output.")
@click.pass_context
def logs(ctx, target, field):
    """Browse run history. Optionally show a specific run: sim logs last"""
    store = _get_store()

    if target:
        try:
            record = store.get(target)
        except FileNotFoundError as e:
            click.echo(f"[sim] error: {e}", err=True)
            sys.exit(1)
        parsed = record.get("parsed_output", {})
        if field:
            if field not in parsed:
                click.echo(f"[sim] error: field '{field}' not found", err=True)
                sys.exit(1)
            if ctx.obj["json"]:
                click.echo(json_mod.dumps({field: parsed[field]}))
            else:
                click.echo(parsed[field])
        else:
            if ctx.obj["json"]:
                click.echo(json_mod.dumps(parsed, indent=2))
            else:
                for k, v in parsed.items():
                    click.echo(f"  {k}: {v}")
    else:
        runs = store.list()
        if not runs:
            if ctx.obj["json"]:
                click.echo("[]")
            else:
                click.echo("[sim] no runs recorded")
            return
        if ctx.obj["json"]:
            click.echo(json_mod.dumps(runs, indent=2))
        else:
            for r in runs:
                status = "ok" if r.get("exit_code", 1) == 0 else "fail"
                click.echo(
                    f"  #{r.get('id', '?')}  {r.get('timestamp', '?')[:19]}  "
                    f"{r.get('solver', '?')}  {status}  {r.get('script', '?')}"
                )
