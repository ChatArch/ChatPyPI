"""Supervisor regressions for configuration and safe protocol adapters."""
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from chatpypi.cli import cli


def test_serve_reads_active_chatenv_and_keeps_cli_override(monkeypatch):
    import chatpypi.config as config
    import chatpypi.service as service
    import chatpypi.service_auth as auth
    import uvicorn
    captured = {}
    monkeypatch.setattr(config, "load_active_pypi_env", lambda *args, **kwargs: {
        "CHATPYPI_AUTH_ISSUER": "https://issuer.example.test",
        "CHATPYPI_AUTH_AUDIENCE": "resource",
        "CHATPYPI_AUTH_JWKS_URL": "https://issuer.example.test/jwks",
        "CHATPYPI_AUTH_SCOPE": "profile-scope",
    })
    class Verifier:
        def __init__(self, **kwargs):
            captured.update(kwargs)
    monkeypatch.setattr(auth, "JWTResourceVerifier", Verifier)
    monkeypatch.setattr(service, "create_app", lambda **kwargs: object())
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    result = CliRunner().invoke(cli, ["--mode", "local", "serve", "--profile-binding", "client=account", "--required-scope", "explicit-scope"])
    assert result.exit_code == 0, result.output
    assert captured["issuer"] == "https://issuer.example.test"
    assert captured["audience"] == "resource"
    assert captured["required_scope"] == "explicit-scope"


def test_remote_probe_excludes_server_paths_and_repository_url():
    from chatpypi.tool_service import build_catalog
    fields = build_catalog(cli)["pkg_probe"].input_schema["properties"]
    assert "project_dir" not in fields
    assert "repository_url" not in fields


def test_invalid_url_has_no_retained_untrusted_exception():
    from chatpypi.service_client import validate_base_url
    with pytest.raises(ValueError) as caught:
        validate_base_url("https://host.test:credential-canary")
    assert "credential-canary" not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


def test_read_only_get_tool_route(monkeypatch):
    from chatpypi.main import RepositoryCheck
    from chatpypi.service import create_app
    monkeypatch.setattr("chatpypi.cli.check_repository_conflicts", lambda *a, **k: [RepositoryCheck("name", "pass", "available")])
    with TestClient(create_app(allow_insecure_test=True)) as client:
        result = client.get("/api/pkg/probe", params={"package_name": "demo"})
        assert result.status_code == 200
        assert result.json()["exit_code"] == 0
        assert client.get("/api/pkg/probe", params={"package_name": "demo", "repository_url": "https://bad.test"}).status_code == 422
        assert client.get("/api/pkg/upload").status_code == 405


def test_remote_probe_requires_name_and_never_reads_server_project(monkeypatch):
    from chatpypi.service import create_app
    from chatpypi.tool_service import build_catalog
    assert "package_name" in build_catalog(cli)["pkg_probe"].input_schema["required"]
    monkeypatch.setattr("chatpypi.cli.read_project_metadata", lambda *args: (_ for _ in ()).throw(AssertionError("server metadata read")))
    with TestClient(create_app(allow_insecure_test=True)) as client:
        assert client.post("/api/pkg/probe", json={}).status_code == 422


def test_all_interface_bind_accepts_explicit_trusted_host(monkeypatch):
    import chatpypi.service as service
    import uvicorn
    captured = {}
    monkeypatch.setattr(service, "create_app", lambda **kwargs: captured.update(kwargs) or object())
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    result = CliRunner().invoke(cli, ["--mode", "local", "serve", "--host", "0.0.0.0", "--allowed-host", "tools.example.test", "--auth-issuer", "https://auth.example.test", "--auth-audience", "chatpypi-service", "--jwks-url", "https://auth.example.test/jwks", "--profile-binding", "client=account"])
    assert result.exit_code == 0, result.output
    assert "tools.example.test" in captured["allowed_hosts"]
    assert "0.0.0.0" not in captured["allowed_hosts"]


def test_jwks_provider_does_not_block_event_loop():
    import asyncio
    import threading
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    from chatpypi.service_auth import JWTResourceVerifier

    seen = []
    def provider():
        seen.append(threading.get_ident())
        return {"keys": []}
    verifier = JWTResourceVerifier(issuer="https://auth.example.test", audience="tools", jwks_provider=provider)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode({}, key, algorithm="RS256", headers={"kid": "missing"})
    async def check():
        event_loop_thread = threading.get_ident()
        assert await verifier.verify_token(token) is None
        assert seen and seen[0] != event_loop_thread
    asyncio.run(check())
