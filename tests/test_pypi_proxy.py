import json
import os

import pytest
import requests
from click.testing import CliRunner
from chatenv.paths import get_paths
from chatenv.store import EnvStore

from chatpypi import config, session_ops
from chatpypi.cli import cli

PROXY = "http://fixed-proxy.example.invalid:8080"


def save_profile(home, name, **values):
    EnvStore(get_paths(home).envs_dir).save_profile(config.PyPIConfig, name, values)


def test_proxy_field_is_registered_sensitive():
    assert config.PyPIConfig.get_fields()["PYPI_PROXY_URL"].is_sensitive


def test_named_proxy_precedes_process_setting_and_honors_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PYPI_PROXY_URL", "http://ambient.example.invalid:8080")
    save_profile(tmp_path, "alpha", PYPI_PROXY_URL=PROXY)
    assert config.resolve_pypi_proxy_url(env_profile="alpha", home=tmp_path) == PROXY


@pytest.mark.parametrize("value", [
    "http://user:CONFIG_CANARY@proxy.example.invalid:bad",
    "http://proxy.example.invalid/?token=CONFIG_CANARY",
    "file:///CONFIG_CANARY",
])
def test_bad_proxy_errors_never_retain_value_or_cause(value):
    with pytest.raises(ValueError) as caught:
        config.resolve_pypi_proxy_url(profile_values={"PYPI_PROXY_URL": value})
    assert "CONFIG_CANARY" not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


def test_loaded_token_uses_matching_profile_without_serializing_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "pypi.org")
    monkeypatch.setenv("no_proxy", "pypi.org")
    save_profile(tmp_path, "alpha", PYPI_PROXY_URL=PROXY)
    save_profile(tmp_path, "beta", PYPI_PROXY_URL="http://other.example.invalid:8080")
    raw = {"provider": "pypi", "username": "alice", "base_url": "https://pypi.org", "cookies": []}
    session_ops.save_session_payload_to_token_store(raw, env_profile="alpha", home=tmp_path)
    loaded = session_ops.load_session_payload_from_token_store(env_profile="alpha", home=tmp_path)
    assert loaded == raw
    assert PROXY not in json.dumps(loaded)
    session = session_ops.requests_session_from_payload(loaded)
    try:
        assert session.proxies == {"http": PROXY, "https": PROXY}
        assert session.trust_env is False
    finally:
        session.close()
    assert os.environ["NO_PROXY"] == "pypi.org"
    token_file = get_paths(tmp_path).home_dir / "tokens/PyPI/alpha.json"
    assert PROXY not in token_file.read_text()


def test_cli_login_reads_profile_proxy_without_exporting_global_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.example.invalid:8080")
    save_profile(tmp_path, "alpha", PYPI_USERNAME="alice", PYPI_PASSWORD="test-password", PYPI_PROXY_URL=PROXY)
    seen = {}

    def fake_login(**kwargs):
        seen.update(kwargs)
        return {"provider": "pypi", "username": "alice", "cookies": []}, "encoded-fixture"

    monkeypatch.setattr("chatpypi.cli.login_to_pypi", fake_login)
    result = CliRunner().invoke(cli, ["auth", "login", "-e", "alpha", "--no-write-token", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert seen["proxy_url"] == PROXY
    assert PROXY not in result.output
    assert os.environ["HTTPS_PROXY"] == "http://ambient.example.invalid:8080"


def test_explicit_login_proxy_overrides_no_proxy_and_keeps_session(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "pypi.org")
    monkeypatch.setenv("no_proxy", "pypi.org")
    instance = requests.Session()
    login_html = '<form action="/account/login/" method="post"><input name="csrf_token" type="hidden" value="fixture"><input name="username"><input name="password" type="password"></form>'
    account = '<h1>Account settings</h1><section id="account-details"><span class="form-group__label">Username</span><p class="form-group__text">alice</p></section><a href="/account/logout/">Log out</a>'

    def get(url, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = (login_html if "/account/login/" in url else account).encode()
        return response

    def post(url, **kwargs):
        return get("https://pypi.org/manage/account/")

    monkeypatch.setattr(instance, "get", get)
    monkeypatch.setattr(instance, "post", post)
    monkeypatch.setattr(session_ops.requests, "Session", lambda: instance)
    payload, _ = session_ops.login_to_pypi(username="alice", password="fixture", proxy_url=PROXY)
    assert payload["username"] == "alice"
    assert instance.proxies == {"http": PROXY, "https": PROXY}
    assert instance.trust_env is False
    assert os.environ["NO_PROXY"] == "pypi.org"


def test_refresh_hook_passes_matching_profile_proxy(tmp_path, monkeypatch):
    save_profile(tmp_path, "alpha", PYPI_USERNAME="alice", PYPI_PASSWORD="fixture", PYPI_PROXY_URL=PROXY)
    seen = {}

    def fake_login(**kwargs):
        seen.update(kwargs)
        return {"provider": "pypi", "username": "alice", "cookies": []}, "fixture"

    monkeypatch.setattr(session_ops, "login_to_pypi", fake_login)
    session_ops.refresh_chatenv_token(service="PyPI", profile="alpha", home=tmp_path)
    assert seen["proxy_url"] == PROXY
