"""Optional FastAPI adapter for the registration-only service."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import hmac
import json
import threading
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from chatpypi.registration import (
    RegistrationError,
    RegistrationManager,
    ServiceConfig,
    load_service_config,
    validate_service_config,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PreflightRequest(_StrictModel):
    names: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        min_length=1, max_length=20
    )
    owner: str = Field(min_length=1, max_length=39)


class PlanRequest(_StrictModel):
    distribution: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=240)
    owner: str = Field(min_length=1, max_length=39)
    visibility: Literal["private", "public"] = "private"


class JobRequest(_StrictModel):
    plan_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(min_length=1, max_length=256)


class HealthResponse(_StrictModel):
    status: Literal["ok"]


class CapabilityConstraints(_StrictModel):
    initial_version: str
    template: Literal["chatarch"]
    default_visibility: Literal["private"]
    public_requires_explicit_plan_field: bool
    automatic_release: bool
    automatic_mutation_replay: bool


class CapabilitiesResponse(_StrictModel):
    service: Literal["chatpypi-registration"]
    api_version: Literal["v1"]
    mode: Literal["registration-only"]
    completion_state: Literal["registered"]
    registration_enabled: bool
    stages: list[str]
    constraints: CapabilityConstraints


class RegistryState(_StrictModel):
    status: Literal["available", "occupied", "unknown"]
    ownership: Literal["owned", "not_owned", "unknown", "not_applicable"]


class RepositoryState(_StrictModel):
    status: Literal["absent", "exists", "unknown"]


class CredentialState(_StrictModel):
    pypi_upload: Literal["ready", "needs_auth", "unknown"]
    pypi_session: Literal["ready", "needs_auth", "unknown"]
    github: Literal["ready", "needs_auth", "unknown"]


class PreflightItem(_StrictModel):
    distribution: str
    normalized_name: str
    module_name: str
    registry: RegistryState
    repository: RepositoryState
    credentials: CredentialState
    github_identity: str | None
    can_plan: bool
    blockers: list[str]


class PreflightResponse(_StrictModel):
    owner: str
    items: list[PreflightItem]
    count: int
    read_only: Literal[True]


class PlanResponse(_StrictModel):
    id: str
    created_at: str
    distribution: str
    normalized_name: str
    module_name: str
    description: str
    owner: str
    repository: str
    visibility: Literal["private", "public"]
    initial_version: str
    requires_python: str
    template: Literal["chatarch"]
    default_branch: Literal["main"]
    workflow_filename: Literal["publish.yml"]
    stages: list[str]
    confirmation: str
    ready: bool
    blockers: list[str]
    digest: str


class SafeJobError(_StrictModel):
    category: str
    message: str


class StageReceipt(_StrictModel):
    stage: str
    status: Literal["completed"]
    at: str
    ready: bool | None = None
    registry: Literal["available"] | None = None
    repository: Literal["absent"] | None = None
    module_name: str | None = None
    file_count: int | None = None
    passed: bool | None = None
    artifacts: list[str] | None = None
    initial_version: str | None = None
    artifact_count: int | None = None
    version: str | None = None
    wheel: bool | None = None
    sdist: bool | None = None
    url: str | None = None
    created: bool | None = None
    visibility: Literal["private", "public"] | None = None
    branch: str | None = None
    pushed: bool | None = None
    active: bool | None = None
    workflow: str | None = None
    default_branch: str | None = None
    default_branch_protected: bool | None = None


class JobResponse(_StrictModel):
    id: str
    plan_id: str
    normalized_name: str
    status: Literal[
        "queued",
        "running",
        "blocked",
        "failed",
        "reconciliation_required",
        "registered",
    ]
    stage: str
    receipts: list[StageReceipt]
    created_at: str
    updated_at: str
    error: SafeJobError | None
    idempotent_replay: bool | None = None


class JobListResponse(_StrictModel):
    items: list[JobResponse]
    count: int
    total: int
    limit: int
    offset: int


class _AuthenticationRequired(RegistrationError):
    def __init__(self):
        super().__init__("needs_auth")
        self.status_code = 401


async def _send_asgi_error(send, category: str, message: str, status_code: int) -> None:
    body = json.dumps(
        {"error": {"category": category, "message": message}},
        separators=(",", ":"),
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared = int(raw_length.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                await _send_asgi_error(
                    send, "invalid_request", "Request validation failed.", 400
                )
                return
            if declared < 0:
                await _send_asgi_error(
                    send, "invalid_request", "Request validation failed.", 400
                )
                return
            if declared > self.max_bytes:
                await _send_asgi_error(
                    send,
                    "body_too_large",
                    "Request body exceeds the service limit.",
                    413,
                )
                return

        received = 0
        messages = []
        message_count = 0
        while True:
            message = await receive()
            if message.get("type") == "http.request":
                message_count += 1
                if message_count > 1024:
                    await _send_asgi_error(
                        send,
                        "body_too_large",
                        "Request body exceeds the service limit.",
                        413,
                    )
                    return
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    await _send_asgi_error(
                        send,
                        "body_too_large",
                        "Request body exceeds the service limit.",
                        413,
                    )
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break
            else:
                messages.append(message)
                break

        async def replay_receive():
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay_receive, send)


class _RateLimitMiddleware:
    _MAX_CLIENT_BUCKETS = 2048

    def __init__(self, app, requests_per_minute: int):
        self.app = app
        self.requests_per_minute = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith(
            "/api/"
        ):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        client_key = str(client[0]) if isinstance(client, tuple) and client else "unknown"
        now = time.monotonic()
        limited = False
        with self._lock:
            if (
                client_key not in self._requests
                and len(self._requests) >= self._MAX_CLIENT_BUCKETS
            ):
                stale = [
                    key
                    for key, values in self._requests.items()
                    if not values or now - values[-1] >= 60.0
                ]
                for key in stale:
                    self._requests.pop(key, None)
                if len(self._requests) >= self._MAX_CLIENT_BUCKETS:
                    client_key = "overflow"
            entries = self._requests[client_key]
            while entries and now - entries[0] >= 60.0:
                entries.popleft()
            if len(entries) >= self.requests_per_minute:
                limited = True
            else:
                entries.append(now)
        if limited:
            await _send_asgi_error(
                send,
                "rate_limited",
                "Request rate limit exceeded.",
                429,
            )
            return
        await self.app(scope, receive, send)


class _SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        response_started = False

        async def secured_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower()
                    not in {b"cache-control", b"x-content-type-options"}
                ]
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                message = dict(message)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, secured_send)
        except Exception:
            if response_started:
                raise
            await _send_asgi_error(
                secured_send,
                "internal_error",
                "The registration service could not complete the request.",
                500,
            )


def _error_response(category: str, message: str, status_code: int) -> JSONResponse:
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if status_code == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status_code,
        content={"error": {"category": category, "message": message}},
        headers=headers,
    )


def create_app(
    *,
    config: ServiceConfig | None = None,
    manager: RegistrationManager | None = None,
) -> FastAPI:
    """Create a secured API app without starting a listener."""

    resolved_config = validate_service_config(config or load_service_config())
    resolved_manager = manager or RegistrationManager(resolved_config)
    request_slots = asyncio.Semaphore(4)

    async def run_blocking(call, *args, **kwargs):
        """Run one bounded sync service call without framework threadpool coupling."""

        async with request_slots:
            completed = threading.Event()
            result: list[tuple[bool, object]] = []

            def worker() -> None:
                try:
                    result.append((True, call(*args, **kwargs)))
                except Exception as exc:
                    result.append((False, exc))
                finally:
                    completed.set()

            thread = threading.Thread(
                target=worker,
                name="chatpypi-api-request",
                daemon=False,
            )
            thread.start()
            while not completed.is_set():
                await asyncio.sleep(0.01)
            thread.join()
            ok, value = result[0]
            if ok:
                return value
            assert isinstance(value, Exception)
            raise value from None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            resolved_manager.close()

    app = FastAPI(
        title="ChatPyPI Registration API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.registration_manager = resolved_manager
    app.state.service_config = resolved_config
    app.add_middleware(_BodyLimitMiddleware, max_bytes=resolved_config.max_body_bytes)
    app.add_middleware(
        _RateLimitMiddleware,
        requests_per_minute=resolved_config.max_requests_per_minute,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(resolved_config.allowed_hosts),
        www_redirect=False,
    )
    app.add_middleware(_SecurityHeadersMiddleware)
    bearer_auth = HTTPBearer(auto_error=False)

    @app.exception_handler(RegistrationError)
    async def registration_error_handler(_request: Request, exc: RegistrationError):
        return _error_response(exc.category, exc.safe_message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _exc: RequestValidationError):
        return _error_response(
            "invalid_request", "Request validation failed.", 422
        )

    async def require_auth(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    ) -> None:
        if request.headers.get("origin") is not None:
            raise RegistrationError("origin_rejected")
        supplied = credentials.credentials if credentials is not None else ""
        if not supplied or not hmac.compare_digest(supplied, resolved_config.api_token):
            raise _AuthenticationRequired()

    secured = [Depends(require_auth)]

    @app.get("/health", include_in_schema=False, response_model=HealthResponse)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/api/capabilities",
        dependencies=secured,
        response_model=CapabilitiesResponse,
    )
    async def capabilities() -> dict:
        return resolved_manager.capabilities()

    @app.get("/api/schema", dependencies=secured, include_in_schema=False)
    async def schema() -> dict:
        return app.openapi()

    @app.post(
        "/api/preflight",
        dependencies=secured,
        response_model=PreflightResponse,
    )
    async def preflight(payload: PreflightRequest) -> dict:
        return await run_blocking(
            resolved_manager.preflight, payload.names, payload.owner
        )

    @app.post(
        "/api/plans",
        dependencies=secured,
        status_code=201,
        response_model=PlanResponse,
    )
    async def create_plan(payload: PlanRequest) -> dict:
        return await run_blocking(resolved_manager.create_plan, payload.model_dump())

    @app.post(
        "/api/jobs",
        dependencies=secured,
        status_code=202,
        response_model=JobResponse,
        response_model_exclude_none=True,
    )
    async def create_job(
        payload: JobRequest,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=16, max_length=128),
        ],
    ) -> dict:
        job, replay = await run_blocking(
            resolved_manager.submit_job,
            payload.plan_id,
            payload.confirmation,
            idempotency_key,
        )
        response = dict(job)
        response["idempotent_replay"] = replay
        return response

    @app.get(
        "/api/jobs",
        dependencies=secured,
        response_model=JobListResponse,
        response_model_exclude_none=True,
    )
    async def list_jobs(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    ) -> dict:
        return await run_blocking(
            resolved_manager.list_jobs, limit=limit, offset=offset
        )

    @app.get(
        "/api/jobs/{job_id}",
        dependencies=secured,
        response_model=JobResponse,
        response_model_exclude_none=True,
    )
    async def get_job(job_id: str) -> dict:
        return await run_blocking(resolved_manager.get_job, job_id)

    return app


__all__ = ["create_app"]
