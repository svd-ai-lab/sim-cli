"""Basic CLI smoke tests."""

import json

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
