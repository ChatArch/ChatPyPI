from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from chatpypi.cli import cli
from chatpypi.config import RegistrationAPIConfig


pytestmark = [pytest.mark.e2e]


def test_chatpypi_serve_is_registered_without_starting_listener():
    runner = CliRunner()
    help_result = runner.invoke(cli, ["--help"])
    tree_result = runner.invoke(cli, ["--tree-brief"])
    serve_help = runner.invoke(cli, ["serve", "--help"])

    assert help_result.exit_code == 0
    assert "serve" in help_result.output
    assert "paths" in help_result.output
    assert tree_result.exit_code == 0
    assert "serve  # Serve the secured registration-only HTTP API." in tree_result.output
    assert serve_help.exit_code == 0
    assert "--host" in serve_help.output
    assert "--port" in serve_help.output


def test_chatpypi_paths_reports_isolated_chatarch_runtime(tmp_path):
    home = tmp_path / "home"
    result = CliRunner().invoke(
        cli,
        ["paths", "--format", "json"],
        env={"CHATARCH_HOME": str(home)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert Path(payload["chatarch_home"]) == home
    assert Path(payload["registration_state"]).is_relative_to(home)


def test_chatpypi_serve_fails_before_listening_without_service_token(
    monkeypatch, tmp_path
):
    for field in RegistrationAPIConfig.get_fields().values():
        monkeypatch.delenv(field.env_key, raising=False)
    result = CliRunner().invoke(
        cli,
        ["serve"],
        env={"CHATARCH_HOME": str(tmp_path / "home")},
    )

    assert result.exit_code != 0
    assert "Service authentication is not configured" in result.output


def test_chatpypi_serve_passes_hardened_single_worker_options(
    monkeypatch, tmp_path
):
    for field in RegistrationAPIConfig.get_fields().values():
        monkeypatch.delenv(field.env_key, raising=False)
    calls = []
    monkeypatch.setattr(
        "chatpypi.api.create_app",
        lambda *, config: {"registration_enabled": config.registration_enabled},
    )
    monkeypatch.setattr(
        "uvicorn.run",
        lambda app, **kwargs: calls.append((app, kwargs)),
    )

    result = CliRunner().invoke(
        cli,
        ["serve"],
        env={
            "CHATARCH_HOME": str(tmp_path / "home"),
            "CHATPYPI_API_TOKEN": "placeholder-service-value",
        },
    )

    assert result.exit_code == 0, result.output
    app, options = calls[0]
    assert app == {"registration_enabled": False}
    assert options == {
        "host": "127.0.0.1",
        "port": 8765,
        "workers": 1,
        "access_log": False,
        "proxy_headers": False,
        "server_header": False,
    }
