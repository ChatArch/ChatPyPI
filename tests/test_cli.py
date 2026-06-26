from click.testing import CliRunner

from chatpypi.cli import cli
from chatpypi.session_ops import encode_session_token


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


def test_version_option_reports_package_version():
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "chatpypi, version 0.2.2" in result.output


def test_auth_session_show_uses_env_session_token(monkeypatch):
    token = encode_session_token(
        {"provider": "pypi", "username": "RexWzh", "cookies": [], "csrf": {"last_seen_token": "token"}}
    )
    monkeypatch.setenv("PYPI_SESSION_TOKEN", token)

    result = CliRunner().invoke(cli, ["auth", "session", "show"])

    assert result.exit_code == 0, result.output
    assert "session_source=PYPI_SESSION_TOKEN" in result.output
    assert "provider=pypi" in result.output
    assert "username=RexWzh" in result.output
