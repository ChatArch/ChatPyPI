from click.testing import CliRunner

from chatpypi.cli import cli


def test_help_lists_pypi_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "auth" in result.output
    assert "profile" in result.output
    assert "config" in result.output
    assert "pkg" in result.output
    assert "project" in result.output
    assert "publisher" in result.output
    assert "token" in result.output
    assert "doctor" in result.output
    assert "docs" in result.output
    assert "init" in result.output
    assert "build" in result.output
    assert "check" in result.output
    assert "probe" in result.output
    assert "upload" in result.output
