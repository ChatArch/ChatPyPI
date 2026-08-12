from click.testing import CliRunner

from chatpypi.cli import cli
from chatpypi.session_ops import save_session_payload_to_token_store


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
    assert "--tree" in result.output


def test_tree_option_prints_registered_pypi_cli_tree():
    result = CliRunner().invoke(cli, ["--tree"])

    assert result.exit_code == 0, result.output
    assert "chatpypi  # Python package lifecycle and PyPI operations helpers" in result.output
    assert "├── --help  # Show help for the current command." in result.output
    assert "├── --version  # Show package version." in result.output
    assert "├── --tree  # Print the registered CLI tree." in result.output
    assert "├── pkg  # Package scaffold/build/check/upload/probe helpers" in result.output
    assert "│   ├── init [NAME] [--template default|chatarch]" in result.output
    assert "├── auth  # Authentication, session, and bootstrap helpers" in result.output
    assert "│   ├── session  # Inspect and manage token-backed PyPI session state" in result.output
    assert "├── publisher  # Read or manage current-account publisher views" in result.output
    assert "└── probe [PACKAGE-NAME]" in result.output


def test_version_option_reports_package_version():
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "chatpypi, version 0.2.10" in result.output


def test_publisher_help_lists_direct_active_commands():
    result = CliRunner().invoke(cli, ["publisher", "--help"])

    assert result.exit_code == 0, result.output
    assert "detail" in result.output
    assert "add-github" in result.output
    assert "pending-add" in result.output
    assert "pending-remove" in result.output


def test_auth_session_show_uses_chatenv_token_store(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    save_session_payload_to_token_store(
        {"provider": "pypi", "username": "RexWzh", "cookies": [], "csrf": {"last_seen_token": "opaque-csrf-fixture"}}
    )

    result = CliRunner().invoke(cli, ["auth", "session", "show"])

    assert result.exit_code == 0, result.output
    assert "session_source=ChatEnv token store" in result.output
    assert "provider=pypi" in result.output
    assert "username=RexWzh" in result.output
