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

def _is_local_host(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1", "")


def _check_local(solver: str) -> dict:
    """Run on-demand detection in this process. Returns the same shape
    as the /detect/{solver} HTTP endpoint."""
    from pathlib import Path

    from sim.compat import load_compatibility, safe_detect_installed

    driver = get_driver(solver)
    if driver is None:
        return {"ok": False, "error": f"unknown solver: {solver}"}

    installs = safe_detect_installed(driver)
    driver_dir = Path(__file__).parent / "drivers" / solver
    resolutions: list[dict] = []
    compat_dict: dict | None = None
    try:
        compat = load_compatibility(driver_dir)
        compat_dict = {
            "driver": compat.driver,
            "sdk_package": compat.sdk_package,
            "profiles": [p.to_dict() for p in compat.profiles],
            "deprecated": [d.to_dict() for d in compat.deprecated],
        }
        for inst in installs:
            r = compat.resolve(inst.version)
            resolutions.append({"install": inst.to_dict(), "resolution": r.to_dict()})
    except FileNotFoundError:
        for inst in installs:
            resolutions.append({"install": inst.to_dict(), "resolution": None})

    return {
        "ok": True,
        "data": {
            "solver": solver,
            "installs": [i.to_dict() for i in installs],
            "resolutions": resolutions,
            "compatibility": compat_dict,
        },
    }


def _check_remote(solver: str, host: str, port: int) -> dict:
    """Hit GET /detect/{solver} on a remote sim serve."""
    import httpx

    from sim.session import _httpx_client

    url = f"http://{host}:{port}/detect/{solver}"
    try:
        with _httpx_client(host, timeout=15.0) as c:
            r = c.get(url)
    except httpx.RequestError as e:
        return {"ok": False, "error": f"cannot reach sim serve at {host}:{port} - {e}"}
    if r.status_code != 200:
        return {"ok": False, "error": f"{r.status_code}: {r.text}"}
    return r.json()


def _render_check(data: dict) -> None:
    """Pretty-print a /detect/{solver} response."""
    solver = data["solver"]
    installs = data.get("installs", [])
    resolutions = data.get("resolutions", [])
    compat = data.get("compatibility")

    click.echo(f"[sim] check: {solver}")
    if not installs:
        click.echo(f"  no {solver} installations detected on this host")
        click.echo(f"  ensure the solver is installed and re-run `sim check {solver}`")
        return

    click.echo(f"  detected {len(installs)} installation(s):\n")
    for entry in resolutions:
        inst = entry["install"]
        res = entry.get("resolution")
        click.echo(f"  - {solver} {inst['version']}")
        click.echo(f"      path:    {inst['path']}")
        click.echo(f"      source:  {inst['source']}")
        if res is None:
            click.echo("      profile: (driver has no compatibility.yaml yet)")
        elif res["status"] == "ok":
            p = res["preferred"]
            click.echo(f"      profile: {p['name']}  (skill rev {p['skill_revision']})")
            click.echo(f"      sdk pin: {p['sdk']}")
            if p.get("extras_alias"):
                click.echo(f"      install: sim env install {p['name']}")
                click.echo(f"               (or: pip install 'sim-cli[{p['extras_alias']}]')")
            if res.get("also_matching"):
                others = ", ".join(p2["name"] for p2 in res["also_matching"])
                click.echo(f"      also OK: {others}")
        else:
            click.echo("      profile: [X] unsupported by any current profile")
            for d in res.get("deprecated_hits", []):
                click.echo(f"               deprecated: {d['profile']} (migrate to {d.get('migrate_to', '?')})")
        click.echo()

    if compat:
        click.echo(f"  driver compatibility.yaml: {compat['driver']} → {compat['sdk_package']}")
        click.echo(f"  available profiles: {', '.join(p['name'] for p in compat['profiles'])}")


@main.command()
@click.argument("solver")
@click.pass_context
def check(ctx, solver):
    """Detect installed versions of a solver and resolve their profile.

    By default scans THIS host. With `--host <ip>` (top-level option),
    asks the remote sim serve to scan its own host.
    """
    host = ctx.obj["host"]
    port = ctx.obj["port"]
    is_local = _is_local_host(host)

    if is_local:
        resp = _check_local(solver)
    else:
        resp = _check_remote(solver, host, port)

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(resp, indent=2, default=str))
        sys.exit(0 if resp.get("ok") else 1)

    if not resp.get("ok"):
        click.echo(f"[sim] check: {resp.get('error', 'unknown error')}", err=True)
        sys.exit(1)

    _render_check(resp["data"])


# ── env (per-profile venv management) ────────────────────────────────────────


@main.group(name="env")
def env_group():
    """Manage isolated profile environments under .sim/envs/."""


@env_group.command("install")
@click.argument("profile")
@click.option("--upgrade", is_flag=True, help="Reinstall even if the env exists.")
@click.option("--quiet", is_flag=True, help="Suppress subprocess output.")
@click.pass_context
def env_install(ctx, profile, upgrade, quiet):
    """Bootstrap a profile env: create venv + install pinned SDK + sim-cli."""
    from sim import env_manager

    try:
        state = env_manager.install(profile, upgrade=upgrade, quiet=quiet)
    except ValueError as e:
        click.echo(f"[sim] env install: {e}", err=True)
        sys.exit(2)
    except RuntimeError as e:
        click.echo(f"[sim] env install failed: {e}", err=True)
        sys.exit(1)

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(state, indent=2, default=str))
    else:
        click.echo(f"[sim] env ready: {state['profile']}")
        click.echo(f"        driver:        {state['driver']}")
        click.echo(f"        sdk:           {state['sdk_package']} {state['sdk_spec']}")
        click.echo(f"        runner module: {state['runner_module']}")
        click.echo(f"        env path:      {state['env_path']}")
        click.echo(f"        backend:       {state['backend']} ({state['install_seconds']}s)")


@env_group.command("list")
@click.option("--catalogue", is_flag=True,
              help="Also show every profile defined in any compatibility.yaml.")
@click.pass_context
def env_list(ctx, catalogue):
    """List bootstrapped profile envs (and optionally the full catalogue)."""
    from sim import env_manager
    from sim.compat import all_known_profiles

    envs = env_manager.list_envs()

    if ctx.obj["json"]:
        out = {"installed": envs}
        if catalogue:
            out["catalogue"] = [
                {
                    "driver": d,
                    **p.to_dict(),
                }
                for d, p in all_known_profiles()
            ]
        click.echo(json_mod.dumps(out, indent=2, default=str))
        return

    if not envs:
        click.echo("[sim] no profile envs bootstrapped yet")
        click.echo("        run `sim env install <profile>` to create one")
    else:
        click.echo(f"[sim] {len(envs)} profile env(s) installed:")
        for st in envs:
            line = f"  - {st.get('profile', '?'):<32} {st.get('status', '?')}"
            if st.get("driver"):
                line += f"  driver={st['driver']}"
            if st.get("sdk_spec"):
                line += f"  sdk={st['sdk_spec']}"
            click.echo(line)
            if st.get("env_path"):
                click.echo(f"      {st['env_path']}")

    if catalogue:
        click.echo()
        click.echo("[sim] available profiles in compatibility.yaml files:")
        installed_names = {st.get("profile") for st in envs}
        for driver_name, prof in all_known_profiles():
            mark = "  installed" if prof.name in installed_names else "             "
            click.echo(f"  - {prof.name:<32} ({driver_name}) {mark}")
            click.echo(f"      sdk: {prof.sdk}   solver: {', '.join(prof.solver_versions)}")


@env_group.command("remove")
@click.argument("profile")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def env_remove(ctx, profile, yes):
    """Tear down a profile env."""
    from sim import env_manager

    target = env_manager.env_path(profile)
    if not target.exists():
        click.echo(f"[sim] env remove: {profile} is not installed", err=True)
        sys.exit(1)

    if not yes:
        click.confirm(f"[sim] remove {target}?", abort=True)

    ok = env_manager.remove(profile, force=True)
    if ctx.obj["json"]:
        click.echo(json_mod.dumps({"ok": ok, "profile": profile}))
    else:
        click.echo(f"[sim] env removed: {profile}")


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
@click.option("--solver", required=True, help="Solver name (e.g. fluent).")
@click.option("--mode", default="meshing", type=click.Choice(["meshing", "solver"]))
@click.option("--ui-mode", default="no_gui", type=click.Choice(["no_gui", "gui"]))
@click.option("--processors", default=1, type=int)
@click.option("--profile", default=None,
              help="Override the profile auto-resolution (e.g. pyfluent_0_38_modern).")
@click.option("--inline", is_flag=True,
              help="Use the legacy in-process driver path (no profile env). Tests/debug.")
@click.option("--auto-install", is_flag=True,
              help="If the resolved profile env is missing, bootstrap it before connecting.")
@click.pass_context
def connect(ctx, solver, mode, ui_mode, processors, profile, inline, auto_install):
    """Launch a solver and hold a persistent session.

    Default flow uses the runner architecture: detects solver installs on
    the target host, resolves a compatibility profile, and (if needed)
    bootstraps an isolated env via `sim env install` before opening the
    session. With --inline, falls back to the legacy in-process path.
    """
    from sim.session import SessionClient

    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    payload = {
        "solver": solver,
        "mode": mode,
        "ui_mode": ui_mode,
        "processors": processors,
    }
    if profile:
        payload["profile"] = profile
    if inline:
        payload["inline"] = True

    result = client.connect(**payload)

    # Auto-bootstrap retry on 409 (env not bootstrapped)
    if (
        not result.get("ok")
        and "not bootstrapped" in str(result.get("error", "")).lower()
        and not inline
    ):
        # Try to derive profile name from the error message or run a check
        click.echo(f"[sim] connect: {result.get('error')}", err=True)
        if not auto_install:
            click.echo(
                "  re-run with --auto-install to bootstrap the profile env automatically",
                err=True,
            )
            sys.exit(2)

        # Use sim check (locally or remotely) to find the profile name
        host = ctx.obj["host"]
        port = ctx.obj["port"]
        check_resp = (
            _check_remote(solver, host, port) if not _is_local_host(host) else _check_local(solver)
        )
        if not check_resp.get("ok"):
            click.echo(f"[sim] connect: cannot resolve profile — {check_resp.get('error')}", err=True)
            sys.exit(1)
        resolutions = check_resp["data"].get("resolutions", [])
        target_profile = None
        for entry in resolutions:
            res = entry.get("resolution") or {}
            if res.get("status") == "ok" and res.get("preferred"):
                target_profile = res["preferred"]["name"]
                break
        if target_profile is None:
            click.echo("[sim] connect: no profile resolved for any detected install", err=True)
            sys.exit(1)

        click.echo(f"[sim] auto-install: bootstrapping {target_profile}...")
        # Bootstrap via the right host
        if _is_local_host(host):
            from sim import env_manager
            try:
                env_manager.install(target_profile, quiet=False)
            except (ValueError, RuntimeError) as e:
                click.echo(f"[sim] auto-install failed: {e}", err=True)
                sys.exit(1)
        else:
            from sim.session import _httpx_client
            with _httpx_client(host, timeout=600.0) as c:
                r = c.post(
                    f"http://{host}:{port}/env/install",
                    json={"profile": target_profile, "upgrade": False},
                )
            if r.status_code != 200:
                click.echo(f"[sim] auto-install failed: {r.status_code} {r.text}", err=True)
                sys.exit(1)

        # Retry the connect
        result = client.connect(**payload)

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        if result.get("ok"):
            click.echo("[sim] connect: session ready")
            if result.get("data"):
                click.echo(json_mod.dumps(result["data"], indent=4, default=str))
        else:
            click.echo(f"[sim] connect: failed - {result.get('error', 'unknown')}", err=True)
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
                type=click.Choice([
                    "session.summary",
                    "session.versions",
                    "session.mode",
                    "last.result",
                    "workflow.summary",
                ]))
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
@click.option(
    "--stop-server",
    is_flag=True,
    help="Also stop the sim-server process after disconnecting (use this when "
         "the server was auto-spawned by `sim connect` and you're done with it).",
)
@click.pass_context
def disconnect(ctx, stop_server):
    """Tear down the active session.

    By default this only ends the solver session inside sim-server. The
    server process keeps running so subsequent `sim connect` calls are
    instant. Pass --stop-server to also kill the server (or use `sim stop`
    on its own).
    """
    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    result = client.disconnect()

    if stop_server:
        # Try to stop the server even if the disconnect failed (e.g. there
        # was no active session) — the user explicitly asked for cleanup.
        stop_result = client.stop()
        # Merge for json output; for human output we just print both lines
        result = {
            "ok": result.get("ok", False) or stop_result.get("ok", False),
            "data": {
                "disconnect": result.get("data") or {"error": result.get("error")},
                "stop": stop_result.get("data") or {"error": stop_result.get("error")},
            },
        }

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        if stop_server:
            click.echo("[sim] disconnected and stopped sim-server")
        elif result.get("ok"):
            sid = result.get("data", {}).get("session_id", "?")
            click.echo(f"[sim] disconnected (session_id={sid})")
        else:
            click.echo(f"[sim] error: {result.get('error')}", err=True)
            sys.exit(1)


# ── stop ─────────────────────────────────────────────────────────────────────

@main.command()
@click.pass_context
def stop(ctx):
    """Stop the sim-server process.

    This is the counterpart to the auto-spawn that `sim connect` does:
    after `sim connect`/`exec`/`disconnect`, run `sim stop` to fully tear
    down the background uvicorn process and free port 7600.

    Disconnects any active session as part of shutdown — there's no need
    to call `sim disconnect` first.
    """
    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"])
    result = client.stop()

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        if result.get("ok"):
            data = result.get("data", {})
            sid = data.get("disconnected_session")
            if sid:
                click.echo(f"[sim] stopped sim-server (also disconnected session {sid})")
            else:
                click.echo("[sim] stopped sim-server")
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
