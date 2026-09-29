from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from chatpypi.cli import cli, main
from chatpypi.mirror_ops import TSINGHUA_URL


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    return {
        "HOME": str(tmp_path / "home"),
        "CHATARCH_HOME": str(tmp_path / "chatarch"),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
    }


def test_mirror_set_and_show_json_status(tmp_path):
    env = _isolated_env(tmp_path)
    runner = CliRunner()
    changed = runner.invoke(
        cli, ["mirror", "set", "tsinghua", "--format", "json"], env=env
    )
    assert changed.exit_code == 0, changed.output
    payload = json.loads(changed.output)
    assert payload["preset"] == "tsinghua"
    assert payload["scope"] == "user"
    assert payload["tools"]["uv"]["status"] == "changed"
    assert payload["tools"]["pip"]["status"] == "changed"

    shown = runner.invoke(cli, ["mirror", "show", "--format", "json"], env=env)
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.output)
    assert payload["tools"]["uv"]["preset"] == "tsinghua"
    assert payload["tools"]["pip"]["preset"] == "tsinghua"


def test_mirror_set_missing_preset_noninteractive_fails_without_writes(tmp_path):
    env = _isolated_env(tmp_path)
    result = CliRunner().invoke(cli, ["mirror", "set", "-I"], env=env)
    assert result.exit_code != 0
    assert "Preset is required" in result.output
    assert not (tmp_path / "xdg").exists()


def test_mirror_set_missing_preset_prompts_through_chatstyle(tmp_path, monkeypatch):
    env = _isolated_env(tmp_path)
    monkeypatch.setattr(
        "chatstyle.core.interactive.is_interactive_available", lambda: True
    )
    monkeypatch.setattr(
        "chatpypi.cli.ask_select",
        lambda message, choices, style=None: "tsinghua - Tsinghua PyPI mirror",
    )
    result = CliRunner().invoke(cli, ["mirror", "set", "--tool", "uv"], env=env)
    assert result.exit_code == 0, result.output
    assert "tsinghua" in result.output


def test_mirror_dry_run_text_does_not_create_config(tmp_path):
    env = _isolated_env(tmp_path)
    result = CliRunner().invoke(
        cli, ["mirror", "set", "default", "--dry-run", "--tool", "uv"], env=env
    )
    assert result.exit_code == 0, result.output
    assert "would-change" in result.output
    assert "USER" in result.output
    assert not (tmp_path / "xdg").exists()


def test_console_wrapper_registers_mirror_instead_of_rewriting_to_init(monkeypatch):
    seen = {}

    def fake_main(*, args, prog_name):
        seen["args"] = args
        seen["prog_name"] = prog_name

    monkeypatch.setattr(cli, "main", fake_main)
    monkeypatch.setattr(sys, "argv", ["chatpypi", "mirror", "show"])
    main()
    assert seen == {"args": ["mirror", "show"], "prog_name": "chatpypi"}


def test_real_console_entrypoint_routes_mirror_and_tree_lists_commands(tmp_path):
    env = os.environ.copy()
    env.update(_isolated_env(tmp_path))
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "src")
    console = Path(sys.executable).with_name("chatpypi")
    command = [str(console)] if console.is_file() else [sys.executable, "-m", "chatpypi.cli"]
    shown = subprocess.run(
        [*command, "mirror", "show", "--format", "json"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["scope"] == "user"

    tree = subprocess.run(
        [*command, "--tree"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert tree.returncode == 0, tree.stderr
    assert "mirror" in tree.stdout
    assert "show" in tree.stdout and "set" in tree.stdout


def test_native_pip_reads_persisted_user_value(tmp_path):
    env = os.environ.copy()
    env.update(_isolated_env(tmp_path))
    env.pop("PIP_INDEX_URL", None)
    env.pop("PIP_CONFIG_FILE", None)
    result = CliRunner().invoke(
        cli, ["mirror", "set", "tsinghua", "--tool", "pip", "-I"], env=env
    )
    assert result.exit_code == 0, result.output
    readback = subprocess.run(
        [sys.executable, "-m", "pip", "config", "get", "global.index-url", "--user"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert readback.returncode == 0, readback.stderr
    assert readback.stdout.strip() == TSINGHUA_URL


def test_native_uv_discovers_persisted_user_config(tmp_path):
    uv = Path("/home/zhihong/.local/bin/uv")
    if not uv.is_file():
        return
    env = os.environ.copy()
    env.update(_isolated_env(tmp_path))
    for key in ("UV_CONFIG_FILE", "UV_DEFAULT_INDEX", "UV_INDEX_URL", "UV_INDEX"):
        env.pop(key, None)
    env["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    result = CliRunner().invoke(
        cli, ["mirror", "set", "tsinghua", "--tool", "uv", "-I"], env=env
    )
    assert result.exit_code == 0, result.output
    readback = subprocess.run(
        [str(uv), "cache", "dir", "-vv"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert readback.returncode == 0, readback.stderr
    expected = tmp_path / "xdg/uv/uv.toml"
    assert f"Found user configuration in: `{expected}`" in readback.stderr
