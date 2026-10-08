import asyncio
import time
from types import SimpleNamespace

from click.testing import CliRunner
from fastapi.testclient import TestClient

from chatpypi.cli import cli
from chatpypi.config import PyPIConfig, resolve_service_settings


def test_service_config_defaults_and_precedence(monkeypatch):
    fields = PyPIConfig.get_fields()
    assert fields["CHATPYPI_MODE"].default == "local"
    assert "CHATPYPI_BASE_URL" in fields
    monkeypatch.setattr(
        "chatpypi.config.load_active_pypi_env",
        lambda home=None: {"CHATPYPI_MODE": "service", "CHATPYPI_BASE_URL": "http://active.test"},
    )
    monkeypatch.setenv("CHATPYPI_MODE", "local")
    monkeypatch.setenv("CHATPYPI_BASE_URL", "http://env.test")
    assert resolve_service_settings()[0:2] == ("local", "http://env.test")
    assert resolve_service_settings(mode="service", base_url="http://arg.test")[0:2] == (
        "service",
        "http://arg.test",
    )


def test_catalog_is_deduplicated_and_policy_bound():
    from chatpypi.tool_service import build_catalog

    catalog = build_catalog(cli)
    assert "pkg_probe" in catalog
    assert "probe" not in catalog
    assert catalog["pkg_probe"].policy == "server"
    assert catalog["pkg_build"].policy == "local"
    assert catalog["mirror_show"].policy == "local"
    assert "project_show" not in catalog
    assert catalog["pkg_upload"].policy == "server"
    assert all(not name.startswith("auth_") for name in catalog)
    assert "env_profile" not in catalog["publisher_detail"].input_schema["properties"]


def test_service_mode_rejects_bad_url_before_credentials(monkeypatch):
    touched = []
    monkeypatch.setattr("chatpypi.service_client.load_access_token", lambda *a, **k: touched.append(True))
    result = CliRunner().invoke(
        cli,
        ["--mode", "service", "--base-url", "not-a-url", "pkg", "probe", "demo"],
    )
    assert result.exit_code != 0
    assert "valid HTTP(S)" in result.output
    assert touched == []


def test_service_mode_dispatches_probe_without_local_fallback(monkeypatch):
    monkeypatch.setattr(
        "chatpypi.service_client.call_remote_tool",
        lambda **kwargs: {"exit_code": 0, "stdout": "[PASS] name: available\n", "stderr": ""},
    )
    monkeypatch.setattr(
        "chatpypi.cli.check_repository_conflicts",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("local fallback")),
    )
    for path in (["pkg", "probe"], ["probe"]):
        result = CliRunner().invoke(
            cli,
            ["--mode", "service", "--base-url", "https://service.test", *path, "demo"],
        )
        assert result.exit_code == 0, result.output
        assert "available" in result.output


def test_service_mode_keeps_declared_local_tool_local(monkeypatch):
    monkeypatch.setattr(
        "chatpypi.mirror_ops.show_mirrors",
        lambda **kwargs: {"tools": {}, "warnings": []},
    )
    monkeypatch.setattr(
        "chatpypi.service_client.call_remote_tool",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("remote dispatch")),
    )
    result = CliRunner().invoke(cli, ["--mode", "service", "mirror", "show", "--format", "json"])
    assert result.exit_code == 0, result.output


def test_client_token_never_falls_back_to_pypi_key(monkeypatch):
    from chatpypi.service_client import load_access_token

    monkeypatch.setenv("PYPI_API_TOKEN", "must-not-be-used")
    monkeypatch.delenv("CHATPYPI_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr("chatpypi.service_client.TokenStore.read", lambda *a, **k: {})
    assert load_access_token("default") is None


def test_http_and_mcp_share_catalog_and_execute_controlled_probe(monkeypatch):
    from chatpypi.main import RepositoryCheck
    from chatpypi.service import create_app, create_mcp_server

    monkeypatch.setattr(
        "chatpypi.cli.check_repository_conflicts",
        lambda *a, **k: [RepositoryCheck("name", "pass", "available")],
    )
    app = create_app(allow_insecure_test=True)
    with TestClient(app) as client:
        response = client.post("/api/pkg/probe", json={"package_name": "demo"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["exit_code"] == 0
        assert "available" in response.json()["stdout"]

    async def smoke():
        server = create_mcp_server()
        names = {tool.name for tool in await server.list_tools()}
        assert "pkg_probe" in names
        result = await server.call_tool("pkg_probe", {"package_name": "demo"})
        assert result.structured_content["exit_code"] == 0

    asyncio.run(smoke())


def test_http_auth_requires_scope_and_server_binding(monkeypatch):
    from chatpypi.service import create_app

    class Verifier:
        async def verify_token(self, token):
            if token == "good":
                return SimpleNamespace(subject="worker", client_id="client", scopes=["chatpypi:invoke"])
            return None

    monkeypatch.setattr(
        "chatpypi.tool_service.invoke_tool",
        lambda name, arguments, **kwargs: {"exit_code": 0, "stdout": "ok\n", "stderr": ""},
    )
    app = create_app(
        token_verifier=Verifier(),
        profile_bindings={"worker": "bound-profile"},
        include_mcp=False,
    )
    client = TestClient(app)
    assert client.post("/api/pkg/probe", json={"package_name": "demo"}).status_code == 401
    denied = client.post(
        "/api/pkg/probe",
        headers={"Authorization": "Bearer bad"},
        json={"package_name": "demo"},
    )
    assert denied.status_code == 401
    accepted = client.post(
        "/api/pkg/probe",
        headers={"Authorization": "Bearer good"},
        json={"package_name": "demo", "env_profile": "attacker"},
    )
    assert accepted.status_code == 422


def test_rs256_verifier_rejects_wrong_audience_scope_and_identity():
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from chatpypi.service_auth import JWTResourceVerifier

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = "test-key"
    verifier = JWTResourceVerifier(
        issuer="https://auth.example",
        audience="chatpypi-service",
        jwks_provider=lambda: {"keys": [jwk]},
    )
    now = int(time.time())

    def token(**overrides):
        claims = {
            "iss": "https://auth.example",
            "aud": "chatpypi-service",
            "iat": now,
            "exp": now + 60,
            "scope": "chatpypi:invoke",
            "sub": "worker",
        }
        claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})

    assert asyncio.run(verifier.verify_token(token())).subject == "worker"
    assert asyncio.run(verifier.verify_token(token(aud="other"))) is None
    assert asyncio.run(verifier.verify_token(token(scope="other"))) is None
    assert asyncio.run(verifier.verify_token(token(sub=None))) is None
