from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import json
from pathlib import Path

import httpx

from chatpypi.api import create_app
from chatpypi.registration import RegistrationManager, ServiceConfig

from test_registration_workflow import FakeBackend, FakeLocalOps


TOKEN = "test-service-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _config(tmp_path: Path, *, enabled: bool = True, body_limit: int = 65536) -> ServiceConfig:
    home = tmp_path / "home"
    return ServiceConfig(
        api_token=TOKEN,
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver", "127.0.0.1", "localhost"),
        allowed_owners=("ChatArch",),
        registration_enabled=enabled,
        chatarch_home=home,
        state_dir=home / "runtime" / "chatpypi" / "registration-api",
        max_body_bytes=body_limit,
    )


def _manager(config: ServiceConfig) -> RegistrationManager:
    return RegistrationManager(
        config,
        backend=FakeBackend([]),
        local_ops=FakeLocalOps([]),
        start_executor=False,
    )


@asynccontextmanager
async def _api_client(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client


def test_health_is_minimal_and_every_api_read_requires_auth(tmp_path):
    config = _config(tmp_path)
    app = create_app(config=config, manager=_manager(config))

    async def scenario():
        async with _api_client(app) as client:
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}
            assert health.headers["cache-control"] == "no-store"
            assert "access-control-allow-origin" not in health.headers

            unauthorized = await client.get("/api/capabilities")
            assert unauthorized.status_code == 401
            assert unauthorized.headers["www-authenticate"] == "Bearer"
            browser = await client.get(
                "/api/capabilities",
                headers={**AUTH, "Origin": "https://frontend.example"},
            )
            assert browser.status_code == 403
            assert browser.json()["error"]["category"] == "origin_rejected"
            capabilities = await client.get("/api/capabilities", headers=AUTH)
            assert capabilities.status_code == 200
            assert capabilities.json()["completion_state"] == "registered"
            assert capabilities.json()["registration_enabled"] is True

            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/redoc")).status_code == 404
            assert (await client.get("/openapi.json")).status_code == 404
            schema = await client.get("/api/schema", headers=AUTH)
            assert schema.status_code == 200
            components = schema.json()["components"]["schemas"]
            assert "PlanRequest" in components
            assert "PlanResponse" in components
            assert "JobResponse" in components
            assert "HTTPBearer" in schema.json()["components"]["securitySchemes"]

    asyncio.run(scenario())


def test_host_body_limit_and_unknown_fields_are_rejected_with_fixed_errors(tmp_path):
    config = _config(tmp_path, body_limit=256)
    app = create_app(config=config, manager=_manager(config))

    async def scenario():
        async with _api_client(app) as client:
            bad_host = await client.get(
                "/health", headers={"Host": "attacker.example"}
            )
            assert bad_host.status_code == 400

            oversized = await client.post(
                "/api/preflight",
                headers={**AUTH, "Content-Type": "application/json"},
                content=json.dumps({"names": ["x" * 300], "owner": "ChatArch"}),
            )
            assert oversized.status_code == 413
            assert oversized.json()["error"]["category"] == "body_too_large"

            unknown = await client.post(
                "/api/preflight",
                headers=AUTH,
                json={
                    "names": ["demo-pkg"],
                    "owner": "ChatArch",
                    "command": "rm -rf /",
                },
            )
            assert unknown.status_code == 422
            assert unknown.json() == {
                "error": {
                    "category": "invalid_request",
                    "message": "Request validation failed.",
                }
            }

    asyncio.run(scenario())


def test_plan_submit_idempotency_and_authenticated_job_reads(tmp_path):
    config = _config(tmp_path)
    manager = _manager(config)
    app = create_app(config=config, manager=manager)

    async def scenario():
        async with _api_client(app) as client:
            preflight = await client.post(
            "/api/preflight",
            headers=AUTH,
            json={"names": ["Demo_Pkg"], "owner": "ChatArch"},
            )
            assert preflight.status_code == 200
            assert preflight.json()["items"][0]["normalized_name"] == "demo-pkg"

            plan_response = await client.post(
            "/api/plans",
            headers=AUTH,
            json={
                "distribution": "Demo_Pkg",
                "description": "A small package",
                "owner": "ChatArch",
                "visibility": "public",
            },
            )
            assert plan_response.status_code == 201
            plan = plan_response.json()

            missing_key = await client.post(
            "/api/jobs",
            headers=AUTH,
            json={"plan_id": plan["id"], "confirmation": plan["confirmation"]},
            )
            assert missing_key.status_code == 422

            wrong = await client.post(
            "/api/jobs",
            headers={**AUTH, "Idempotency-Key": "idem-api-registration-0001"},
            json={"plan_id": plan["id"], "confirmation": "wrong"},
            )
            assert wrong.status_code == 409
            assert wrong.json()["error"]["category"] == "confirmation_mismatch"

            submit_headers = {
                **AUTH,
                "Idempotency-Key": "idem-api-registration-0002",
            }
            created = await client.post(
            "/api/jobs",
            headers=submit_headers,
            json={"plan_id": plan["id"], "confirmation": plan["confirmation"]},
            )
            assert created.status_code == 202
            first = created.json()
            assert first["idempotent_replay"] is False

            replay = await client.post(
            "/api/jobs",
            headers=submit_headers,
            json={"plan_id": plan["id"], "confirmation": plan["confirmation"]},
            )
            assert replay.status_code == 202
            assert replay.json()["id"] == first["id"]
            assert replay.json()["idempotent_replay"] is True

            manager.run_job(first["id"])
            assert (await client.get(f"/api/jobs/{first['id']}")).status_code == 401
            detail = await client.get(f"/api/jobs/{first['id']}", headers=AUTH)
            assert detail.status_code == 200
            assert detail.json()["status"] == "registered"
            assert detail.json()["receipts"][-1]["stage"] == "github_readback"
            listing = await client.get("/api/jobs?limit=10&offset=0", headers=AUTH)
            assert listing.status_code == 200
            assert listing.json()["count"] == 1

    asyncio.run(scenario())


def test_registration_gate_defaults_to_read_only(tmp_path):
    config = _config(tmp_path, enabled=False)
    manager = _manager(config)
    app = create_app(config=config, manager=manager)

    async def scenario():
        async with _api_client(app) as client:
            plan = (
                await client.post(
            "/api/plans",
            headers=AUTH,
            json={
                "distribution": "demo-pkg",
                "description": "A small package",
                "owner": "ChatArch",
                "visibility": "private",
            },
                )
            ).json()
            response = await client.post(
            "/api/jobs",
            headers={**AUTH, "Idempotency-Key": "idem-api-registration-0003"},
            json={"plan_id": plan["id"], "confirmation": plan["confirmation"]},
            )
            assert response.status_code == 403
            assert response.json()["error"]["category"] == "registration_disabled"

    asyncio.run(scenario())


def test_unexpected_api_exception_is_fixed_and_redacted(monkeypatch, tmp_path):
    config = _config(tmp_path)
    manager = _manager(config)

    def fail_safely():
        raise RuntimeError("private path and credential-like debug detail")

    monkeypatch.setattr(manager, "capabilities", fail_safely)
    app = create_app(config=config, manager=manager)

    async def scenario():
        async with _api_client(app) as client:
            response = await client.get("/api/capabilities", headers=AUTH)
            assert response.status_code == 500
            assert response.json() == {
                "error": {
                    "category": "internal_error",
                    "message": "The registration service could not complete the request.",
                }
            }
            assert "private path" not in response.text

    asyncio.run(scenario())


def test_chunked_body_and_api_rate_are_bounded(tmp_path):
    config = replace(
        _config(tmp_path, body_limit=128), max_requests_per_minute=2
    )
    app = create_app(config=config, manager=_manager(config))

    async def oversized_chunks():
        yield b'{"names":["'
        yield b"x" * 200
        yield b'"],"owner":"ChatArch"}'

    async def scenario():
        async with _api_client(app) as client:
            oversized = await client.post(
                "/api/preflight",
                headers={**AUTH, "Content-Type": "application/json"},
                content=oversized_chunks(),
            )
            assert oversized.status_code == 413
            assert oversized.json()["error"]["category"] == "body_too_large"

            first = await client.get("/api/capabilities", headers=AUTH)
            assert first.status_code == 200
            limited = await client.get("/api/capabilities", headers=AUTH)
            assert limited.status_code == 429
            assert limited.json()["error"]["category"] == "rate_limited"
            assert (await client.get("/health")).status_code == 200

    asyncio.run(scenario())
