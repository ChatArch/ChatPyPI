import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from click.testing import CliRunner

from chatpypi.cli import cli


def test_upload_catalog_uses_artifacts_not_paths_or_secret_selectors():
    from chatpypi.tool_service import build_catalog

    schema = build_catalog(cli)["pkg_upload"].input_schema
    assert set(schema["properties"]) == {"artifacts", "repository", "skip_existing"}
    assert schema["required"] == ["artifacts"]
    assert schema["properties"]["repository"]["enum"] == ["testpypi", "pypi"]


def test_remote_upload_reads_only_managed_distributions(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "demo-1.0-py3-none-any.whl").write_bytes(b"wheel")
    (dist / "demo-1.0.tar.gz").write_bytes(b"sdist")
    (dist / "ignore.txt").write_text("source", encoding="utf-8")
    captured = {}

    class Response:
        status_code = 200
        content = b'{}'
        is_redirect = False

        def json(self):
            return {"exit_code": 0, "stdout": "Uploaded distributions:\n", "stderr": ""}

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, *, json, headers):
            captured.update(url=url, json=json, headers=headers)
            return Response()

    monkeypatch.setattr("chatpypi.service_client.httpx.Client", Client)
    monkeypatch.setattr("chatpypi.service_client.load_access_token", lambda *a, **k: "access")
    result = CliRunner().invoke(
        cli,
        [
            "--mode", "service", "--base-url", "https://service.test",
            "pkg", "upload", "--project-dir", str(tmp_path), "--skip-existing",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["url"].endswith("/api/pkg/upload")
    assert captured["client"]["follow_redirects"] is False
    assert captured["json"]["skip_existing"] is True
    assert {item["filename"] for item in captured["json"]["artifacts"]} == {
        "demo-1.0-py3-none-any.whl", "demo-1.0.tar.gz"
    }
    assert "project_dir" not in captured["json"]


def test_remote_upload_rejects_symlink_and_credential_selectors(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    target = tmp_path / "outside.whl"
    target.write_bytes(b"wheel")
    (dist / "linked.whl").symlink_to(target)
    monkeypatch.setattr(
        "chatpypi.service_client.load_access_token",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("credential lookup")),
    )
    result = CliRunner().invoke(
        cli,
        ["--mode", "service", "--base-url", "https://service.test", "pkg", "upload", "--project-dir", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "symbolic links" in result.output

    result = CliRunner().invoke(
        cli,
        ["--mode", "service", "--base-url", "https://service.test", "pkg", "upload", "--token-env", "PYPI_API_TOKEN"],
    )
    assert result.exit_code != 0
    assert "not accepted in service mode" in result.output


def test_server_upload_uses_bound_profile_redacts_and_cleans(monkeypatch):
    from chatpypi.main import CommandResult
    from chatpypi.tool_service import invoke_tool

    seen = {}
    monkeypatch.setattr(
        "chatpypi.config.load_pypi_env_profile",
        lambda profile: {"PYPI_API_TOKEN": "provider-canary"} if profile == "bound" else {},
    )

    def fake_upload(project_dir, dist_dir, **kwargs):
        files = sorted(Path(dist_dir).iterdir())
        seen.update(project_dir=Path(project_dir), files=files, kwargs=kwargs)
        return CommandResult([], 0, "provider-canary uploaded", ""), files

    monkeypatch.setattr("chatpypi.main.upload_distributions", fake_upload)
    result = invoke_tool(
        "pkg_upload",
        {
            "artifacts": [{
                "filename": "demo-1.0-py3-none-any.whl",
                "content_base64": "d2hlZWw=",
                "size": 5,
                "sha256": "ba59926159d2aa256eb8739b8da7e2b574b960e1202c6d624cbe981cef996c91",
            }],
            "repository": "pypi",
        },
        bound_profile="bound",
    )
    assert result["exit_code"] == 0
    assert "provider-canary" not in result["stdout"]
    assert "[REDACTED]" in result["stdout"]
    assert seen["kwargs"]["username"] == "__token__"
    assert seen["kwargs"]["repository_url"] is None
    assert seen["kwargs"]["env"] == {
        "TWINE_PASSWORD": "provider-canary",
        "TWINE_NON_INTERACTIVE": "1",
    }
    assert not seen["project_dir"].exists()


def test_http_requires_auth_and_disables_schema_ui():
    from chatpypi.service import create_app

    with pytest.raises(ValueError, match="token_verifier"):
        create_app()
    app = create_app(allow_insecure_test=True, include_mcp=False)
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None


def test_nonloopback_http_rejected_before_token_lookup(monkeypatch):
    from chatpypi.service_client import validate_base_url

    assert validate_base_url("http://127.0.0.1:9000") == "http://127.0.0.1:9000"
    with pytest.raises(ValueError, match="HTTPS"):
        validate_base_url("http://service.test")


def test_fastapi_lifespan_runs_mcp_and_offloads_tool(monkeypatch):
    from chatpypi.service import create_app

    events = []

    class Manager:
        @asynccontextmanager
        async def run(self):
            events.append("start")
            yield
            events.append("stop")

    class MCP:
        session_manager = Manager()

        def streamable_http_app(self, **kwargs):
            from starlette.applications import Starlette
            return Starlette()

    monkeypatch.setattr("chatpypi.service.create_mcp_server", lambda **kwargs: MCP())
    monkeypatch.setattr(
        "chatpypi.tool_service.invoke_tool",
        lambda *args, **kwargs: {"exit_code": 0, "stdout": "ok\n", "stderr": ""},
    )

    async def smoke():
        app = create_app(allow_insecure_test=True)
        async with app.router.lifespan_context(app):
            assert events == ["start"]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                response = await client.post("/api/pkg/probe", json={"package_name": "demo"})
                assert response.status_code == 200
        assert events == ["start", "stop"]

    asyncio.run(smoke())
