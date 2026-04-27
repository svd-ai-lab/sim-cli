"""sim CLI — unified interface for LLM agents to control CAD/CAE simulation software."""
from __future__ import annotations

import json as json_mod
import os
import sys
from pathlib import Path

import click

from sim import __version__, config as _cfg, history as _history
from sim.drivers import get_driver
from sim.runner import execute_script


# ── Top-level group ──────────────────────────────────────────────────────────

@click.group()
@click.version_option(version=__version__)
@click.option("--json", "output_json", is_flag=True, help="JSON output for all commands.")
@click.option("--host", default=None,
              help="Remote sim-server host (e.g. 100.90.110.79). "
                   "Default: SIM_HOST env > config [server].host > localhost.")
@click.option("--port", default=None, type=int,
              help="sim-server port. Default: SIM_PORT env > config [server].port > 7600.")
@click.option("--session", "session_id", default=None,
              help="Target session id (multi-session). "
                   "Default: SIM_SESSION env > server's sole session.")
@click.pass_context
def main(ctx, output_json, host, port, session_id):
    """sim — unified CLI for LLM agents to control CAD/CAE simulation software."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = output_json
    # Flag > env > config > default. --host on the CLI wins because it is
    # the most immediate caller intent. For the host side, "localhost" is
    # the conventional default that triggers auto-start behavior in
    # session.py; don't change that when config says otherwise unless the
    # user explicitly asked.
    ctx.obj["host"] = host or os.environ.get("SIM_HOST") or "localhost"
    ctx.obj["port"] = port if port is not None else _cfg.resolve_server_port()
    ctx.obj["session"] = session_id or os.environ.get("SIM_SESSION") or None


# ── serve ────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--host", "serve_host", default="127.0.0.1",
              help="Bind address. Use 0.0.0.0 for Tailscale/network access.")
@click.option("--port", "serve_port", default=7600, type=int)
@click.option("--reload", is_flag=True, default=False,
              help="Auto-reload on code changes (dev mode).")
def serve(serve_host, serve_port, reload):
    """Start the sim HTTP server (like ollama serve)."""
    import uvicorn

    click.echo(f"[sim] server starting on {serve_host}:{serve_port}")
    if serve_host == "0.0.0.0":
        click.echo("[sim] accessible on network (Tailscale)")
    if reload:
        click.echo("[sim] auto-reload enabled (watching for file changes)")
    uvicorn.run(
        "sim.server:app",
        host=serve_host,
        port=serve_port,
        log_level="info",
        reload=reload,
    )


# ── check ────────────────────────────────────────────────────────────────────

def _is_local_host(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1", "")


def _check_local(solver: str) -> dict:
    """Run on-demand detection in this process. Returns the same shape
    as the /detect/{solver} HTTP endpoint."""
    from pathlib import Path

    from sim.compat import load_compatibility, safe_detect_installed

    try:
        driver = get_driver(solver)
    except Exception as e:  # noqa: BLE001 — surface lazy-import failures distinctly
        return {"ok": False, "error": f"driver '{solver}' failed to load: {type(e).__name__}: {e}"}
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
        }
        for inst in installs:
            profile = compat.resolve(inst.version)
            resolutions.append({
                "install": inst.to_dict(),
                "profile": profile.to_dict() if profile else None,
            })
    except FileNotFoundError:
        for inst in installs:
            resolutions.append({"install": inst.to_dict(), "profile": None})

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
        profile = entry.get("profile")
        click.echo(f"  - {solver} {inst['version']}")
        click.echo(f"      path:    {inst['path']}")
        click.echo(f"      source:  {inst['source']}")
        simulink = inst.get("extra", {}).get("simulink_installed")
        if simulink is True:
            click.echo(f"      simulink: installed")
        elif simulink is False:
            click.echo(f"      simulink: not found on disk")
        if profile is None:
            if compat is None:
                click.echo("      profile: (driver has no compatibility.yaml yet)")
            else:
                click.echo("      profile: [X] unsupported by any current profile")
        else:
            click.echo(f"      profile: {profile['name']}")
            if profile.get("sdk"):
                click.echo(f"      sdk pin: {profile['sdk']}")
        click.echo()

    if compat:
        sdk_label = compat.get("sdk_package") or "(SDK-less)"
        click.echo(f"  driver compatibility.yaml: {compat['driver']} → {sdk_label}")
        click.echo(f"  available profiles: {', '.join(p['name'] for p in compat['profiles'])}")


def _check_all_local() -> dict:
    """Aggregate safe_detect_installed() across every registered driver.

    Returns a flat list of solver entries. Installed drivers emit one row
    per detected installation (using SolverInstall.to_dict() shape, plus
    status="ok"). Drivers with no installation emit a single stub row
    with status="not_installed". Driver errors are captured as status="error".
    """
    from sim.compat import safe_detect_installed
    from sim.drivers import iter_drivers

    rows: list[dict] = []
    for reg_name, driver, import_error in iter_drivers():
        if import_error is not None:
            rows.append({
                "name": reg_name, "status": "error",
                "message": f"{type(import_error).__name__}: {import_error}",
            })
            continue
        name = getattr(driver, "name", driver.__class__.__name__)
        try:
            installs = safe_detect_installed(driver)
        except Exception as e:  # should not happen — safe_* already swallows
            rows.append({"name": name, "status": "error", "message": f"{type(e).__name__}: {e}"})
            continue
        if not installs:
            rows.append({"name": name, "status": "not_installed"})
            continue
        for inst in installs:
            entry = inst.to_dict()
            entry["status"] = "ok"
            rows.append(entry)

    # Stable ordering: alphabetical by driver name, then version descending.
    rows.sort(key=lambda r: (r["name"], _version_sort_key(r.get("version"))))
    return {"ok": True, "data": {"solvers": rows}}


def _version_sort_key(v: str | None) -> tuple:
    """Sort key that places higher versions first (for same driver name)."""
    if not v:
        return (1, "")  # unversioned / not_installed entries go last
    return (0, tuple(-int(p) if p.isdigit() else p for p in v.replace("v", "").split(".")))


def _render_check_all(data: dict) -> None:
    """Pretty-print the aggregated `sim check` output."""
    rows = data.get("solvers", [])
    installed = [r for r in rows if r.get("status") == "ok"]
    missing = [r for r in rows if r.get("status") == "not_installed"]
    errored = [r for r in rows if r.get("status") == "error"]

    click.echo(f"[sim] check: scanned {len(set(r['name'] for r in rows))} drivers")
    click.echo(f"  installed: {len(installed)}  not_installed: {len(missing)}  error: {len(errored)}")
    click.echo()
    if installed:
        click.echo("  installed:")
        for r in installed:
            ver = r.get("version", "?")
            src = r.get("source", "")
            path = r.get("path", "")
            click.echo(f"    {r['name']:<14} {ver:<12} {src:<28} {path}")
        click.echo()
    if errored:
        click.echo("  errors:")
        for r in errored:
            click.echo(f"    {r['name']:<14} {r.get('message', '')}")
        click.echo()
    if missing:
        click.echo(f"  not installed ({len(missing)}): {', '.join(r['name'] for r in missing)}")


@main.command()
@click.argument("solver", required=False)
@click.option("--all", "check_all", is_flag=True, default=False,
              help="Explicitly aggregate across all drivers. Same as passing no solver argument.")
@click.pass_context
def check(ctx, solver, check_all):
    """Detect installed versions of a solver and resolve their profile.

    With SOLVER given, checks that one driver (existing behaviour).
    With no SOLVER (or --all), enumerates every registered driver and
    returns the aggregated installation list.

    By default scans THIS host. With `--host <ip>` (top-level option),
    asks the remote sim serve to scan its own host.
    """
    host = ctx.obj["host"]
    port = ctx.obj["port"]
    is_local = _is_local_host(host)

    if solver is None or check_all:
        if not is_local:
            click.echo("[sim] check --all: remote aggregation not yet implemented; "
                       "pass a specific solver name to query a remote host.", err=True)
            sys.exit(2)
        resp = _check_all_local()
        if ctx.obj["json"]:
            click.echo(json_mod.dumps(resp, indent=2, default=str))
            sys.exit(0 if resp.get("ok") else 1)
        _render_check_all(resp["data"])
        sys.exit(0)

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


# ── lint ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("script", type=click.Path(exists=True))
@click.pass_context
def lint(ctx, script):
    """Validate a simulation script before execution."""
    script_path = Path(script)
    from sim.drivers import iter_drivers

    driver = None
    for _name, d, import_error in iter_drivers():
        if import_error is not None or d is None:
            continue
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
    try:
        driver = get_driver(solver)
    except Exception as e:  # noqa: BLE001 — surface lazy-import failures distinctly
        click.echo(f"[sim] error: driver '{solver}' failed to load: {type(e).__name__}: {e}", err=True)
        sys.exit(1)
    if driver is None:
        click.echo(f"[sim] error: no driver for '{solver}'", err=True)
        sys.exit(1)

    result = execute_script(Path(script), solver=solver, driver=driver)
    parsed = driver.parse_output(result.stdout)

    run_id = _history.append({
        "cwd": str(Path.cwd()),
        "solver": solver,
        "session_id": "",   # one-shot runs have no session
        "kind": "run",
        "label": Path(script).name,
        "script": str(script),
        "ok": result.exit_code == 0,
        "duration_ms": int(result.duration_s * 1000),
        "error": (result.stderr or None) if result.exit_code != 0 else None,
        "parsed_output": parsed,
        "workspace_delta": result.workspace_delta,
    })

    # Persist raw stdout/stderr to disk so the agent can use grep/tail/awk
    # directly without going through `sim logs --field`. Path is
    # deterministic (`<sim_home>/runs/<id>.{stdout,stderr}`) so
    # `sim logs <id> --field stdout` can find it without us storing the
    # path in history.jsonl.
    stdout_path, stderr_path = _write_run_outputs(run_id, result)

    if ctx.obj["json"]:
        data = result.to_dict()
        data["id"] = run_id
        data["parsed_output"] = parsed
        data["stdout_path"] = str(stdout_path) if stdout_path else None
        data["stderr_path"] = str(stderr_path) if stderr_path else None
        click.echo(json_mod.dumps(data, indent=2))
    else:
        status = "converged" if result.ok else "failed"
        click.echo(f"[sim] run:    {script} via {solver}")
        click.echo(f"[sim] status: {status} ({result.duration_s}s)")
        click.echo(f"[sim] log:    saved as #{run_id}")
        # Workspace delta: tell the agent which files this run produced
        # (mesh, time directories, log.simpleFoam, postProcessing, …).
        # ALWAYS print, not just on failure: agents need this to know
        # where to look for KPIs even when the run succeeded. Gating it
        # on failure forces successful agents to guess and `ls` blindly.
        _print_workspace_delta(result.workspace_delta)
        if result.exit_code != 0:
            # Stdout/stderr tail is debugging info; surfaces inline only
            # on failure so successful runs don't dump 10K log lines
            # into the agent's context. Full content is in the raw files
            # listed by _print_followup_hints below either way.
            tail_lines = 20
            if result.stderr:
                stderr_tail = "\n".join(result.stderr.splitlines()[-tail_lines:])
                click.echo(f"[sim] stderr (last {tail_lines} lines):\n{stderr_tail}")
            if result.stdout:
                stdout_tail = "\n".join(result.stdout.splitlines()[-tail_lines:])
                click.echo(f"[sim] stdout (last {tail_lines} lines):\n{stdout_tail}")
        # Drill-in hints: where to find the full run record + any
        # workspace files that look like solver logs. ALWAYS print:
        # successful runs need to point the agent at log.simpleFoam
        # (for KPI extraction) just as much as failed ones do (for
        # debugging). Same hint, different motivation.
        _print_followup_hints(run_id, stdout_path, stderr_path,
                              result.workspace_delta)
    sys.exit(result.exit_code)


def _write_run_outputs(run_id: str, result):
    """Persist full stdout/stderr to disk for grep-friendly access.

    Files land under ``<sim_home>/runs/<id>.{stdout,stderr}``. Empty
    streams are not written (returns None for that side). Failures here
    are swallowed — file persistence must not break the run reporting.
    """
    from sim.config import sim_home
    runs_dir = sim_home() / "runs"
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None, None
    stdout_path = stderr_path = None
    if result.stdout:
        stdout_path = runs_dir / f"{run_id}.stdout"
        try:
            stdout_path.write_text(result.stdout, encoding="utf-8")
        except OSError:
            stdout_path = None
    if result.stderr:
        stderr_path = runs_dir / f"{run_id}.stderr"
        try:
            stderr_path.write_text(result.stderr, encoding="utf-8")
        except OSError:
            stderr_path = None
    return stdout_path, stderr_path


def _print_workspace_delta(delta, max_inline: int = 10):
    """Print up to ``max_inline`` workspace changes; mention overflow."""
    if not delta:
        return
    click.echo(f"[sim] workspace files written ({len(delta)}):")
    for entry in delta[:max_inline]:
        kb = entry["size"] / 1024
        size = f"{kb:.1f} KB" if kb >= 1 else f"{entry['size']} B"
        click.echo(f"        {entry['kind']:8s}  {entry['path']}  ({size})")
    if len(delta) > max_inline:
        click.echo(f"        ... and {len(delta) - max_inline} more")


def _print_followup_hints(run_id, stdout_path, stderr_path, delta):
    """Tell the agent how to drill in further without guessing CLI flags."""
    click.echo("[sim] for more detail:")
    if stdout_path:
        click.echo(f"        cat {stdout_path}                 # full stdout (grep-friendly)")
    if stderr_path:
        click.echo(f"        cat {stderr_path}                 # full stderr")
    click.echo(f"        sim logs {run_id}                          # all fields summary")
    click.echo(f"        sim logs {run_id} --field workspace        # full file list")
    if delta:
        # Suggest the largest workspace file as a likely diagnostic source.
        click.echo(f"        cat {delta[0]['path']}     # likely solver log (largest write)")


# ── connect (persistent session) ────────────────────────────────────────────

@main.command()
@click.option("--solver", required=True, help="Solver name (e.g. fluent).")
@click.option("--mode", default="meshing", type=click.Choice(["meshing", "solver"]))
@click.option("--ui-mode", default="no_gui", type=click.Choice(["no_gui", "gui"]))
@click.option("--processors", default=1, type=int)
@click.option("--workspace", default=None,
              help="Solver-specific working dir (e.g. flotherm FLOUSERDIR).")
@click.pass_context
def connect(ctx, solver, mode, ui_mode, processors, workspace):
    """Launch a solver and hold a persistent session."""
    from sim.session import SessionClient

    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"],
                           session_id=ctx.obj.get("session"))
    result = client.connect(
        solver=solver,
        mode=mode,
        ui_mode=ui_mode,
        processors=processors,
        workspace=workspace,
    )

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
    else:
        if result.get("ok"):
            data = result.get("data") or {}
            sid = data.get("session_id", "?")
            click.echo(f"[sim] connect: session ready (id={sid})")
            click.echo(f"[sim] hint: use `sim --session {sid} ...` or set SIM_SESSION={sid}")
            if data:
                click.echo(json_mod.dumps(data, indent=4, default=str))
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
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"],
                           session_id=ctx.obj.get("session"))
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
@click.argument("name", default="session.summary")
@click.pass_context
def inspect(ctx, name):
    """Query live session state.

    Common targets across all drivers:
      session.summary, session.versions, session.mode, last.result, workflow.summary

    Driver-specific targets (resolved by the driver's query() method):
      ls_dyna:    deck.summary, deck.text, workdir.files, results.summary
      mechanical: mechanical.project_directory, mechanical.files, mechanical.product_info
      fluent:     field.catalog, workflow.summary
      ...
    """
    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"],
                           session_id=ctx.obj.get("session"))
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
    """List active sessions.

    Shape: {sessions: [...], default_session, server_pid}. The 'default'
    session is the one that applies to per-session calls when neither
    --session nor X-Sim-Session is set.
    """
    from sim.session import SessionClient
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"],
                           session_id=ctx.obj.get("session"))
    result = client.status()

    if ctx.obj["json"]:
        click.echo(json_mod.dumps(result, indent=2, default=str))
        return

    # Server may be unreachable (no 'sessions' key when an error dict is returned).
    if "sessions" not in result:
        click.echo(f"[sim] ps: {result.get('error', 'unreachable')}", err=True)
        sys.exit(1)

    sessions = result.get("sessions") or []
    default = result.get("default_session")
    if not sessions:
        click.echo("[sim] no active sessions")
        return
    click.echo(f"[sim] {len(sessions)} session(s) — default: {default or '(none; set --session)'}")
    for s in sessions:
        marker = "*" if s["session_id"] == default else " "
        click.echo(
            f"  {marker} {s['session_id']:<10}  {s['solver']:<10}  "
            f"mode={s.get('mode','-')}  ui={s.get('ui_mode','-')}  "
            f"runs={s.get('run_count', 0)}  profile={s.get('profile') or '-'}"
        )


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
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"],
                           session_id=ctx.obj.get("session"))
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
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"],
                           session_id=ctx.obj.get("session"))
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
    client = SessionClient(host=ctx.obj["host"], port=ctx.obj["port"],
                           session_id=ctx.obj.get("session"))
    result = client.screenshot()

    if not result.get("ok"):
        click.echo(f"[sim] error: {result.get('error')}", err=True)
        sys.exit(1)

    png_bytes = base64.b64decode(result["data"]["base64"])
    out_path = Path(output)
    out_path.write_bytes(png_bytes)
    w, h = result["data"]["width"], result["data"]["height"]
    click.echo(f"[sim] screenshot saved: {out_path} ({w}x{h})")


# ── config ───────────────────────────────────────────────────────────────────


@main.group()
def config():
    """Inspect and manage the two-tier sim config.

    Resolution order: env var > .sim/config.toml > ~/.sim/config.toml > default.
    With no config files present, behavior is unchanged from pre-config sim.
    """


@config.command("path")
@click.pass_context
def config_path(ctx):
    """Print the paths of both config files (whether they exist or not)."""
    paths = {
        "global": str(_cfg.global_config_path()),
        "project": str(_cfg.project_config_path()),
        "global_exists": _cfg.global_config_path().is_file(),
        "project_exists": _cfg.project_config_path().is_file(),
        "history": str(_cfg.history_path()),
    }
    if ctx.obj["json"]:
        click.echo(json_mod.dumps(paths, indent=2))
    else:
        mark = lambda b: "(exists)" if b else "(absent)"  # noqa: E731
        click.echo(f"  global:  {paths['global']}  {mark(paths['global_exists'])}")
        click.echo(f"  project: {paths['project']}  {mark(paths['project_exists'])}")
        click.echo(f"  history: {paths['history']}")


@config.command("show")
@click.pass_context
def config_show(ctx):
    """Print the merged (effective) config."""
    _cfg.clear_cache()
    merged = _cfg.load_config()
    if ctx.obj["json"]:
        click.echo(json_mod.dumps({
            "merged": merged,
            "server_port": _cfg.resolve_server_port(),
            "server_host": _cfg.resolve_server_host(),
        }, indent=2))
    else:
        click.echo(f"  server.host: {_cfg.resolve_server_host()}")
        click.echo(f"  server.port: {_cfg.resolve_server_port()}")
        solvers = _cfg.list_solver_pins()
        if solvers:
            click.echo("  solver pins:")
            for name, pin in solvers.items():
                parts = [f"{k}={v!r}" for k, v in pin.items()]
                click.echo(f"    {name}: {', '.join(parts)}")
        else:
            click.echo("  solver pins: (none)")


@config.command("init")
@click.option("--scope", default="project", type=click.Choice(["project", "global"]),
              help="Which config file to create (default: project).")
@click.pass_context
def config_init(ctx, scope):
    """Create a stub config file. Safe: does not overwrite existing files."""
    path = _cfg.init_config_file(scope)
    if ctx.obj["json"]:
        click.echo(json_mod.dumps({"ok": True, "path": str(path), "scope": scope}))
    else:
        click.echo(f"[sim] config: wrote {scope} stub at {path}")


# ── logs (run history) ───────────────────────────────────────────────────────

@main.command()
@click.argument("target", required=False)
@click.option("--field", help="Extract a specific field from run parsed output.")
@click.option("--solver", "filter_solver", help="Only show runs of this solver.")
@click.option("--session", "filter_session", help="Only show runs of this session id.")
@click.option("--all", "show_all", is_flag=True,
              help="Show runs across all projects (default: current cwd only).")
@click.option("--limit", default=50, type=int, help="Max rows to show (default 50).")
@click.pass_context
def logs(ctx, target, field, filter_solver, filter_session, show_all, limit):
    """Browse global run history at ~/.sim/history.jsonl.

    By default lists runs recorded from the current project (cwd filter).
    Pass --all for a global view, or filter with --solver / --session.
    Use `sim logs last` to see the most recent run; `sim logs <run_id>`
    for a specific one.
    """
    cwd_filter = None if show_all else str(Path.cwd())

    if target:
        record = _history.get_by_id(target, cwd=cwd_filter)
        if record is None:
            click.echo(f"[sim] error: no run '{target}' found", err=True)
            sys.exit(1)
        parsed = record.get("parsed_output") or {}
        if field:
            # Resolution order:
            #   1. stdout / stderr → read raw file at <sim_home>/runs/<id>.<field>
            #      (we don't inline these into history.jsonl — too big)
            #   2. top-level record key (covers workspace_delta, ok, etc.)
            #   3. parsed_output key (per-driver fields)
            # Synonym: `workspace` → `workspace_delta` for ergonomics.
            value = _MISSING = object()
            if field in ("stdout", "stderr"):
                from sim.config import sim_home
                p = sim_home() / "runs" / f"{record.get('run_id')}.{field}"
                if p.is_file():
                    value = p.read_text(encoding="utf-8")
                else:
                    value = ""  # empty stream OR pre-v3 record without files
            else:
                top_alias = {"workspace": "workspace_delta"}
                key = top_alias.get(field, field)
                if key in record:
                    value = record[key]
                elif field in parsed:
                    value = parsed[field]
                else:
                    click.echo(f"[sim] error: field '{field}' not found", err=True)
                    sys.exit(1)
            if ctx.obj["json"]:
                click.echo(json_mod.dumps({field: value}, default=str))
            else:
                if isinstance(value, (list, dict)):
                    click.echo(json_mod.dumps(value, indent=2, default=str))
                else:
                    click.echo(value)
        else:
            if ctx.obj["json"]:
                click.echo(json_mod.dumps(parsed, indent=2))
            else:
                for k, v in parsed.items():
                    click.echo(f"  {k}: {v}")
        return

    runs = _history.read(
        cwd=cwd_filter,
        solver=filter_solver,
        session_id=filter_session,
        limit=limit,
    )
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
            status = "ok" if r.get("ok") else "fail"
            ts = (r.get("ts") or "")[:19]
            rid = r.get("run_id", "?")
            solver = r.get("solver") or "-"
            kind = r.get("kind", "-")
            label = r.get("script") or r.get("label") or ""
            click.echo(f"  #{rid}  {ts}  {solver:<10} {kind:<5} {status:<4} {label}")
