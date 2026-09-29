from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from chatpypi.mirror_ops import (
    DEFAULT_URL,
    TSINGHUA_URL,
    MirrorConfigError,
    resolve_user_config_paths,
    set_mirrors,
    show_mirrors,
)


def test_native_linux_paths_respect_xdg(tmp_path):
    home = tmp_path / "home"
    paths = resolve_user_config_paths(
        home=home,
        platform="linux",
        env={"XDG_CONFIG_HOME": str(tmp_path / "xdg")},
    )

    assert paths.uv == tmp_path / "xdg/uv/uv.toml"
    assert paths.pip == tmp_path / "xdg/pip/pip.conf"
    assert paths.pip_legacy == home / ".pip/pip.conf"


def test_native_macos_pip_paths_follow_documented_existing_directory_rules(tmp_path):
    home = tmp_path / "home"
    data_home = tmp_path / "data"
    (data_home / "pip").mkdir(parents=True)
    paths = resolve_user_config_paths(
        home=home,
        platform="darwin",
        env={"XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_DATA_HOME": str(data_home)},
    )
    assert paths.uv == tmp_path / "config/uv/uv.toml"
    assert paths.pip == data_home / "pip/pip.conf"

    library = home / "Library/Application Support/pip"
    library.mkdir(parents=True)
    paths = resolve_user_config_paths(home=home, platform="darwin", env={})
    assert paths.pip == library / "pip.conf"


def test_native_windows_paths_use_appdata(tmp_path):
    paths = resolve_user_config_paths(
        home=tmp_path / "home",
        platform="win32",
        env={"APPDATA": str(tmp_path / "roaming")},
    )
    assert paths.uv == tmp_path / "roaming/uv/uv.toml"
    assert paths.pip == tmp_path / "roaming/pip/pip.ini"
    assert paths.pip_legacy == tmp_path / "home/pip/pip.ini"


def test_set_both_preserves_uv_comments_private_indexes_and_pip_options(tmp_path):
    uv_path = tmp_path / "uv.toml"
    pip_path = tmp_path / "pip.conf"
    uv_path.write_text(
        "# keep this comment\ncache-dir = \"cache\"\n\n[[index]]\n"
        "name = \"private\"\nurl = \"https://user:secret@example.invalid/simple\"\n"
        "explicit = true\n",
        encoding="utf-8",
    )
    pip_path.write_text(
        "# pip comment\n[global]\ntimeout = 30\n\n[install]\nno-compile = yes\n",
        encoding="utf-8",
    )

    result = set_mirrors(
        "tsinghua", uv_path=uv_path, pip_path=pip_path, pip_legacy_path=tmp_path / "legacy"
    )

    assert result["tools"]["uv"]["status"] == "changed"
    assert result["tools"]["pip"]["status"] == "changed"
    uv_text = uv_path.read_text(encoding="utf-8")
    assert "# keep this comment" in uv_text
    assert 'name = "private"' in uv_text
    assert 'url = "https://user:secret@example.invalid/simple"' in uv_text
    assert f'url = "{TSINGHUA_URL}"' in uv_text
    assert "default = true" in uv_text
    pip_text = pip_path.read_text(encoding="utf-8")
    assert "timeout = 30" in pip_text
    assert "[install]" in pip_text and "no-compile = yes" in pip_text
    assert f"index-url = {TSINGHUA_URL}" in pip_text


def test_both_presets_and_idempotency(tmp_path):
    uv_path = tmp_path / "uv.toml"
    pip_path = tmp_path / "pip.conf"
    kwargs = {"uv_path": uv_path, "pip_path": pip_path, "pip_legacy_path": tmp_path / "legacy"}

    set_mirrors("tsinghua", **kwargs)
    first = set_mirrors("default", **kwargs)
    before = (uv_path.read_bytes(), pip_path.read_bytes())
    second = set_mirrors("default", **kwargs)

    assert first["tools"]["uv"]["url"] == DEFAULT_URL
    assert first["tools"]["pip"]["url"] == DEFAULT_URL
    assert second["tools"]["uv"]["status"] == "unchanged"
    assert second["tools"]["pip"]["status"] == "unchanged"
    assert before == (uv_path.read_bytes(), pip_path.read_bytes())


def test_existing_file_modes_are_preserved(tmp_path):
    uv_path = tmp_path / "uv.toml"
    pip_path = tmp_path / "pip.conf"
    uv_path.write_text("", encoding="utf-8")
    pip_path.write_text("", encoding="utf-8")
    uv_path.chmod(0o640)
    pip_path.chmod(0o600)

    set_mirrors(
        "default", uv_path=uv_path, pip_path=pip_path, pip_legacy_path=tmp_path / "legacy"
    )

    assert uv_path.stat().st_mode & 0o777 == 0o640
    assert pip_path.stat().st_mode & 0o777 == 0o600


def test_dry_run_creates_no_files_or_directories(tmp_path):
    root = tmp_path / "missing"
    result = set_mirrors(
        "tsinghua",
        uv_path=root / "uv/uv.toml",
        pip_path=root / "pip/pip.conf",
        pip_legacy_path=root / "legacy/pip.conf",
        dry_run=True,
    )
    assert result["tools"]["uv"]["status"] == "would-change"
    assert result["tools"]["pip"]["status"] == "would-change"
    assert not root.exists()


def test_malformed_requested_config_prevents_partial_write(tmp_path):
    uv_path = tmp_path / "uv.toml"
    pip_path = tmp_path / "pip.conf"
    uv_path.write_text('cache-dir = "before"\n', encoding="utf-8")
    pip_path.write_text("not an ini file\n", encoding="utf-8")

    with pytest.raises(MirrorConfigError, match="Unable to parse pip user configuration"):
        set_mirrors(
            "tsinghua", uv_path=uv_path, pip_path=pip_path, pip_legacy_path=tmp_path / "legacy"
        )

    assert uv_path.read_text(encoding="utf-8") == 'cache-dir = "before"\n'


def test_custom_uv_default_and_custom_legacy_override_are_safe_conflicts(tmp_path):
    uv_path = tmp_path / "uv.toml"
    uv_path.write_text(
        '[[index]]\nname = "company"\nurl = "https://token@example.invalid/simple"\n'
        "default = true\n",
        encoding="utf-8",
    )
    with pytest.raises(MirrorConfigError, match="custom uv default index"):
        set_mirrors("default", tool="uv", uv_path=uv_path)
    assert "token@example.invalid" in uv_path.read_text(encoding="utf-8")

    uv_path.write_text('index-url = "https://example.invalid/simple"\n', encoding="utf-8")
    with pytest.raises(MirrorConfigError, match="custom uv legacy index setting"):
        set_mirrors("default", tool="uv", uv_path=uv_path)


def test_known_uv_legacy_settings_migrate_to_modern_default_index(tmp_path):
    uv_path = tmp_path / "uv.toml"
    uv_path.write_text(
        f'index-url = "{DEFAULT_URL}"\n[pip]\nindex-url = "{DEFAULT_URL}"\nno-build = true\n',
        encoding="utf-8",
    )
    set_mirrors("tsinghua", tool="uv", uv_path=uv_path)
    text = uv_path.read_text(encoding="utf-8")
    assert "[[index]]" in text and f'url = "{TSINGHUA_URL}"' in text
    assert "index-url" not in text
    assert "no-build = true" in text


def test_show_redacts_custom_urls_and_reports_override_names_only(tmp_path):
    uv_path = tmp_path / "uv.toml"
    pip_path = tmp_path / "pip.conf"
    secret = "https://user:token@example.invalid/simple"
    uv_path.write_text(f'[[index]]\nurl = "{secret}"\ndefault = true\n', encoding="utf-8")
    pip_path.write_text(f"[global]\nindex-url = {secret}\n", encoding="utf-8")
    env = {
        "UV_DEFAULT_INDEX": secret,
        "UV_INDEX": secret,
        "PIP_INDEX_URL": secret,
        "PIP_EXTRA_INDEX_URL": secret,
        "IRRELEVANT_SECRET": secret,
    }

    result = show_mirrors(
        uv_path=uv_path,
        pip_path=pip_path,
        pip_legacy_path=tmp_path / "legacy",
        env=env,
    )
    rendered = json.dumps(result)
    assert secret not in rendered
    assert result["scope"] == "user"
    assert result["tools"]["uv"]["preset"] == "custom"
    assert result["tools"]["uv"]["url"] == "REDACTED"
    assert set(result["override_keys"]) == {
        "UV_DEFAULT_INDEX", "UV_INDEX", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"
    }


def test_pip_show_uses_legacy_value_only_when_current_value_is_absent(tmp_path):
    current = tmp_path / "pip.conf"
    legacy = tmp_path / "legacy.conf"
    legacy.write_text(f"[global]\nindex-url = {TSINGHUA_URL}\n", encoding="utf-8")
    result = show_mirrors(tool="pip", pip_path=current, pip_legacy_path=legacy)
    assert result["tools"]["pip"]["preset"] == "tsinghua"
    assert result["tools"]["pip"]["source"] == "legacy-user"


def test_refuses_existing_leaf_symlink(tmp_path):
    target = tmp_path / "real.toml"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "uv.toml"
    link.symlink_to(target)
    with pytest.raises(MirrorConfigError, match="symbolic link"):
        set_mirrors("default", tool="uv", uv_path=link)


def test_transaction_rolls_back_uv_if_pip_replace_fails(tmp_path, monkeypatch):
    from chatpypi import mirror_ops

    uv_path = tmp_path / "uv.toml"
    pip_path = tmp_path / "pip.conf"
    uv_path.write_text('cache-dir = "before"\n', encoding="utf-8")
    pip_path.write_text("[global]\ntimeout = 3\n", encoding="utf-8")
    real_replace = os.replace
    failed = False

    def fail_pip_once(src, dst):
        nonlocal failed
        if Path(dst) == pip_path and not failed:
            failed = True
            raise OSError("simulated private path detail")
        return real_replace(src, dst)

    monkeypatch.setattr(mirror_ops.os, "replace", fail_pip_once)
    with pytest.raises(MirrorConfigError, match="transaction failed"):
        set_mirrors(
            "tsinghua", uv_path=uv_path, pip_path=pip_path, pip_legacy_path=tmp_path / "legacy"
        )
    assert uv_path.read_text(encoding="utf-8") == 'cache-dir = "before"\n'
    assert pip_path.read_text(encoding="utf-8") == "[global]\ntimeout = 3\n"
