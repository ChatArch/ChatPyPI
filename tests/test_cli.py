from click.testing import CliRunner
from chatstyle import render_click_tree

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
    assert "--tree-brief" in result.output


def test_tree_options_print_registered_pypi_cli_tree():
    full = CliRunner().invoke(cli, ["--tree"])
    brief = CliRunner().invoke(cli, ["--tree-brief"])

    assert full.exit_code == 0, full.output
    assert brief.exit_code == 0, brief.output
    assert full.output.rstrip("\n") == render_click_tree(
        cli, root_name="chatpypi"
    )
    assert brief.output.rstrip("\n") == render_click_tree(
        cli, root_name="chatpypi", brief=True
    )
    assert full.output.startswith("chatpypi\n")
    assert "├── --tree" in full.output
    assert "├── --tree-brief" in full.output
    assert "pkg  # Package scaffold/build/check/upload/probe helpers." in full.output
    assert "init [NAME] [--template TEMPLATE]" in full.output
    assert "publisher  # Read or manage current-account publisher views." in full.output
    assert brief.output.startswith("chatpypi\n")
    assert "init  # Scaffold a minimal src-layout Python package." in brief.output
    assert "publisher  # Read or manage current-account publisher views." in brief.output
    assert "init [NAME]" not in brief.output
    assert "[--template TEMPLATE]" not in brief.output


def test_version_option_reports_package_version():
    result = CliRunner().invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "chatpypi, version 0.2.11" in result.output


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
