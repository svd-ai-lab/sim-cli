"""Basic CLI smoke tests."""

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
