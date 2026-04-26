"""Basic CLI smoke tests."""

import json
import subprocess
import sys

from click.testing import CliRunner

from sim.cli import main


def test_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    from importlib.metadata import version

    assert version("sim-cli") in result.output


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "sim" in result.output


def test_python_m_sim_invocation():
    """``python -m sim --version`` must reach the same Click group as the
    ``sim`` console script. CliRunner-based tests don't exercise the module-
    execution path; this is the regression test for ``src/sim/__main__.py``,
    which exists so dev users can launch ``sim serve`` without holding a
    Windows file lock on ``Scripts/sim.exe`` during ``uv sync``.
    """
    from importlib.metadata import version

    result = subprocess.run(
        [sys.executable, "-m", "sim", "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    # Click reports prog_name as "python -m sim" here (sys.argv[0] is the
    # module path); accept either form alongside the actual version string.
    assert "version" in result.stdout
    assert version("sim-runtime") in result.stdout


def test_check_all_json_shape():
    """`sim check` with no solver arg returns aggregated JSON across all drivers."""
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "check"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    solvers = payload["data"]["solvers"]
    assert isinstance(solvers, list) and len(solvers) > 0

    # every row has name + status; status is one of ok / not_installed / error
    for row in solvers:
        assert "name" in row
        assert row.get("status") in {"ok", "not_installed", "error"}
        if row["status"] == "ok":
            # installed rows inherit SolverInstall.to_dict() keys
            for k in ("version", "path", "source"):
                assert k in row, f"installed row missing {k}: {row}"

    # at least one driver known to be in DRIVERS should appear
    names = {row["name"] for row in solvers}
    assert "openfoam" in names

    # ordering is stable: by name alphabetical
    names_list = [row["name"] for row in solvers]
    # adjacent entries with the same name are allowed (multiple installs);
    # across unique names the order must be non-decreasing
    seen_names: list[str] = []
    for n in names_list:
        if seen_names and seen_names[-1] == n:
            continue
        seen_names.append(n)
    assert seen_names == sorted(seen_names), f"not alphabetical: {seen_names}"


def test_check_all_flag_same_as_no_arg():
    """`sim check --all` produces the same shape as `sim check`."""
    runner = CliRunner()
    r1 = runner.invoke(main, ["--json", "check"])
    r2 = runner.invoke(main, ["--json", "check", "--all"])
    assert r1.exit_code == 0 and r2.exit_code == 0
    assert json.loads(r1.output) == json.loads(r2.output)


def test_run_failure_surfaces_stdout_tail(tmp_path):
    """When a sim run script crashes with errors on stdout (not stderr),
    the CLI should print the stdout tail so the agent can debug without
    a separate `sim logs` round-trip."""
    script = tmp_path / "crash.py"
    script.write_text(
        "print('starting blockMesh...')\n"
        "print('Error: blockMesh failed!')\n"
        "import sys; sys.exit(1)\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--solver", "pybamm", str(script)])
    assert result.exit_code != 0
    assert "[sim] status: failed" in result.output
    assert "blockMesh failed" in result.output
    assert "[sim] stdout (last" in result.output


def test_run_failure_lists_workspace_delta(tmp_path, monkeypatch):
    """Files written by the script during the run must show up under
    `workspace files written` so the agent knows where solver-side log
    files (log.simpleFoam etc.) live."""
    monkeypatch.setenv("SIM_HOME", str(tmp_path / "sim_home"))
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "writes_log.py"
    script.write_text(
        "with open('solver.log', 'w') as f:\n"
        "    f.write('FOAM FATAL ERROR: missing 0/p\\n')\n"
        "import sys; sys.exit(1)\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--solver", "pybamm", str(script)])
    assert result.exit_code != 0
    assert "[sim] workspace files written" in result.output
    assert "solver.log" in result.output
    assert "for more detail" in result.output


def test_run_success_also_lists_workspace_delta(tmp_path, monkeypatch):
    """On SUCCESS the agent still needs to see what was written —
    otherwise it has to `ls` blindly to find time directories,
    log files, postProcessing outputs. Gating workspace delta on
    failure forces successful agents into guessing loops."""
    monkeypatch.setenv("SIM_HOME", str(tmp_path / "sim_home"))
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "writes_then_succeeds.py"
    script.write_text(
        "import os; os.makedirs('postProcessing/sample/100', exist_ok=True)\n"
        "open('postProcessing/sample/100/U.csv', 'w').write('0.5,-0.21\\n')\n"
        "open('log.simpleFoam', 'w').write('Final residual = 1e-6\\n')\n"
        "print('done')\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--solver", "pybamm", str(script)])
    assert result.exit_code == 0
    assert "[sim] status: converged" in result.output
    # Workspace delta MUST appear on success — that's the whole point of
    # the fix. Without it the agent doesn't know where the solver wrote.
    assert "[sim] workspace files written" in result.output
    assert "log.simpleFoam" in result.output
    assert "postProcessing/sample/100/U.csv" in result.output
    # Drill-in hints also fire on success.
    assert "for more detail" in result.output


def test_run_persists_stdout_to_grep_friendly_file(tmp_path, monkeypatch):
    """sim_home/runs/<id>.stdout should hold the full stdout for grep."""
    monkeypatch.setenv("SIM_HOME", str(tmp_path / "sim_home"))
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "noisy.py"
    script.write_text(
        "for i in range(50): print(f'line {i}: residual = 1e-{i}')\n"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["run", "--solver", "pybamm", str(script)])
    assert result.exit_code == 0
    runs_dir = tmp_path / "sim_home" / "runs"
    files = list(runs_dir.glob("*.stdout"))
    assert files, "no .stdout file was written"
    content = files[0].read_text()
    assert "line 0:" in content and "line 49:" in content


def test_logs_field_workspace_returns_delta(tmp_path, monkeypatch):
    """`sim logs <id> --field workspace` returns the file delta as JSON."""
    monkeypatch.setenv("SIM_HOME", str(tmp_path / "sim_home"))
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "writer.py"
    script.write_text("open('a.dat','w').write('x'); open('b.dat','w').write('y')\n")
    runner = CliRunner()
    r1 = runner.invoke(main, ["run", "--solver", "pybamm", str(script)])
    assert r1.exit_code == 0
    # Pull the run_id from the "saved as #N" line.
    rid = None
    for line in r1.output.splitlines():
        if "saved as #" in line:
            rid = line.split("#", 1)[1].strip()
            break
    assert rid is not None
    r2 = runner.invoke(main, ["logs", rid, "--field", "workspace"])
    assert r2.exit_code == 0
    assert "a.dat" in r2.output and "b.dat" in r2.output


def test_logs_field_stdout_reads_persisted_file(tmp_path, monkeypatch):
    """`sim logs <id> --field stdout` should read the raw file (since
    history.jsonl doesn't store stdout inline)."""
    monkeypatch.setenv("SIM_HOME", str(tmp_path / "sim_home"))
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "shout.py"
    script.write_text("print('UNIQUE_NEEDLE_SENTINEL')\n")
    runner = CliRunner()
    r1 = runner.invoke(main, ["run", "--solver", "pybamm", str(script)])
    assert r1.exit_code == 0
    rid = next(l.split("#", 1)[1].strip() for l in r1.output.splitlines() if "saved as #" in l)
    r2 = runner.invoke(main, ["logs", rid, "--field", "stdout"])
    assert r2.exit_code == 0
    assert "UNIQUE_NEEDLE_SENTINEL" in r2.output
