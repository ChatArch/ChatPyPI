from click.testing import CliRunner

from chatpypi.cli import cli


def test_help_lists_pypi_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "init" in result.output
    assert "build" in result.output
    assert "check" in result.output
    assert "probe" in result.output
    assert "upload" in result.output
