from configparser import ConfigParser
from pathlib import Path

import pytest

from chatpypi import mirror_ops
from chatpypi.mirror_ops import DEFAULT_URL, TSINGHUA_URL, MirrorConfigError


@pytest.mark.parametrize("setting", [
    "index-url: https://old.example.invalid/simple\n",
    "index_url = https://old.example.invalid/simple\n",
    "index-url =\n    https://old.example.invalid/simple\n",
])
def test_pip_native_option_forms_are_replaced_without_duplicates(tmp_path, setting):
    path = tmp_path / "pip.conf"
    path.write_text("[global]\ntimeout = 31\n" + setting + "[install]\nno-compile = yes\n")
    mirror_ops.set_mirrors("tsinghua", tool="pip", pip_path=path,
                           pip_legacy_path=tmp_path / "missing", env={})
    parser = ConfigParser(interpolation=None)
    parser.read(path)
    values = [value for key, value in parser.items("global")
              if key.replace("_", "-").lower() == "index-url"]
    assert values == [TSINGHUA_URL]
    assert parser.get("global", "timeout") == "31"
    assert parser.get("install", "no-compile") == "yes"


def test_pip_show_recognizes_native_underscore_option(tmp_path):
    path = tmp_path / "pip.conf"
    path.write_text(f"[global]\nindex_url = {TSINGHUA_URL}\n")
    result = mirror_ops.show_mirrors(tool="pip", pip_path=path,
                                    pip_legacy_path=tmp_path / "missing", env={})
    assert result["tools"]["pip"]["preset"] == "tsinghua"


def test_pip_section_names_remain_case_sensitive(tmp_path):
    path = tmp_path / "pip.conf"
    path.write_text("[GLOBAL]\nindex-url = https://old.example.invalid/simple\n")
    mirror_ops.set_mirrors("default", tool="pip", pip_path=path,
                           pip_legacy_path=tmp_path / "missing", env={})
    parser = ConfigParser(interpolation=None)
    parser.read(path)
    assert parser.get("global", "index-url") == DEFAULT_URL
    assert parser.get("GLOBAL", "index-url") == "https://old.example.invalid/simple"


@pytest.mark.parametrize("tool,content", [
    ("pip", b"PRIVATE_CONFIG_CANARY without section\n"),
    ("uv", b"key = \"PRIVATE_CONFIG_CANARY\n"),
    ("pip", b"PRIVATE_CONFIG_CANARY\xff"),
])
def test_parse_errors_do_not_retain_sensitive_exception_context(tmp_path, tool, content):
    path = tmp_path / "config"
    path.write_bytes(content)
    with pytest.raises(MirrorConfigError) as caught:
        mirror_ops.show_mirrors(tool=tool, uv_path=path, pip_path=path,
                                pip_legacy_path=tmp_path / "missing", env={})
    assert "PRIVATE_CONFIG_CANARY" not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


def test_named_uv_default_is_not_retargeted_with_auth_binding(tmp_path):
    uv_path = tmp_path / "uv.toml"
    pip_path = tmp_path / "pip.conf"
    original = f'[[index]]\nname = "private"\nurl = "{DEFAULT_URL}"\ndefault = true\nauthenticate = "always"\n'
    uv_path.write_text(original)
    with pytest.raises(MirrorConfigError, match="named"):
        mirror_ops.set_mirrors("tsinghua", uv_path=uv_path, pip_path=pip_path,
                               pip_legacy_path=tmp_path / "missing",
                               env={"UV_INDEX_PRIVATE_PASSWORD": "PRIVATE_CONFIG_CANARY"})
    assert uv_path.read_text() == original
    assert not pip_path.exists()


def test_macos_pip_fallback_ignores_xdg_config_home_like_native_pip(tmp_path):
    home = tmp_path / "home"
    paths = mirror_ops.resolve_user_config_paths(
        home=home, platform="darwin", env={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
    assert paths.uv == tmp_path / "xdg/uv/uv.toml"
    assert paths.pip == home / ".config/pip/pip.conf"


def test_transaction_error_does_not_retain_io_exception_context(tmp_path, monkeypatch):
    real_replace = mirror_ops.os.replace
    pip_path = tmp_path / "pip.conf"
    failed = False

    def fail_once(src, dst):
        nonlocal failed
        if Path(dst) == pip_path and not failed:
            failed = True
            raise OSError("PRIVATE_CONFIG_CANARY")
        return real_replace(src, dst)

    monkeypatch.setattr(mirror_ops.os, "replace", fail_once)
    with pytest.raises(MirrorConfigError) as caught:
        mirror_ops.set_mirrors("default", uv_path=tmp_path / "uv.toml", pip_path=pip_path,
                               pip_legacy_path=tmp_path / "missing", env={})
    assert caught.value.__context__ is None
    assert not (tmp_path / "uv.toml").exists()


def test_two_tools_cannot_write_one_config_path(tmp_path):
    path = tmp_path / "config"
    with pytest.raises(MirrorConfigError, match="distinct"):
        mirror_ops.set_mirrors("default", uv_path=path, pip_path=path,
                               pip_legacy_path=tmp_path / "missing", env={})
    assert not path.exists()
