"""Importable REST and MCP adapters over the ChatPyPI Click tool catalog."""

from contextlib import asynccontextmanager
from functools import partial
import inspect
from typing import Any, Literal

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ConfigDict, create_model

from chatpypi import __version__
from chatpypi import tool_service
from chatpypi.cli import cli
from chatpypi.service_auth import bound_profile


def _python_type(schema: dict[str, Any]):
    if "enum" in schema:
        return Literal.__getitem__(tuple(schema["enum"]))
    return {
        "boolean": bool,
        "integer": int,
        "number": float,
        "array": list[dict[str, Any]],
        "object": dict[str, Any],
    }.get(schema.get("type"), str)


def _input_model(spec):
    required = set(spec.input_schema.get("required", ()))
    fields = {}
    for name, field in spec.input_schema["properties"].items():
        annotation = _python_type(field)
        if name in required:
            fields[name] = (annotation, ...)
        else:
            fields[name] = (annotation | None, field.get("default"))
    return create_model(
        f"{spec.name.title().replace('_', '')}Input",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


async def _authorize(request, verifier, bindings, required_scope, default_profile):
    if verifier is None:
        return default_profile
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer access token required")
    access = await verifier.verify_token(header[7:])
    if access is None:
        raise HTTPException(status_code=401, detail="Access token rejected")
    if required_scope not in getattr(access, "scopes", []):
        raise HTTPException(status_code=403, detail="Required scope is missing")
    profile = bound_profile(access, bindings)
    if profile is None:
        raise HTTPException(status_code=403, detail="Authenticated caller has no PyPI profile binding")
    return profile


class _BodyLimitMiddleware:
    def __init__(self, app, limit=30 * 1024 * 1024):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            length = dict(scope.get("headers", [])).get(b"content-length")
            if length:
                try:
                    if int(length) > self.limit:
                        response = JSONResponse({"detail": "Request body too large"}, status_code=413)
                        await response(scope, receive, send)
                        return
                except ValueError:
                    response = JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
                    await response(scope, receive, send)
                    return
            messages = []
            size = 0
            while True:
                message = await receive()
                messages.append(message)
                if message.get("type") == "http.request":
                    size += len(message.get("body", b""))
                    if size > self.limit:
                        response = JSONResponse({"detail": "Request body too large"}, status_code=413)
                        await response(scope, receive, send)
                        return
                    if not message.get("more_body", False):
                        break
                else:
                    break

            async def replay():
                if messages:
                    return messages.pop(0)
                return {"type": "http.disconnect"}

            await self.app(scope, replay, send)
            return
        await self.app(scope, receive, send)


def create_app(
    *,
    token_verifier=None,
    profile_bindings: dict[str, str] | None = None,
    default_profile: str | None = None,
    required_scope: str = "chatpypi:invoke",
    allowed_hosts: list[str] | None = None,
    include_mcp: bool = True,
    allow_insecure_test: bool = False,
) -> FastAPI:
    """Create a bounded tool service without reading credentials on import."""

    if token_verifier is None and not allow_insecure_test:
        raise ValueError("token_verifier is required for the HTTP service")
    if token_verifier is not None and not profile_bindings:
        raise ValueError("Authenticated HTTP service requires profile_bindings")
    bindings = dict(profile_bindings or {})
    mcp_server = None
    if include_mcp:
        mcp_server = create_mcp_server(
            token_verifier=token_verifier,
            profile_bindings=bindings,
            required_scope=required_scope,
        )

    @asynccontextmanager
    async def lifespan(app):
        app.state.tool_limiter = anyio.CapacityLimiter(4)
        if mcp_server is None:
            yield
        else:
            async with mcp_server.session_manager.run():
                yield

    app = FastAPI(
        title="ChatPyPI tool service",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts or ["127.0.0.1", "localhost", "testserver"],
    )
    app.add_middleware(_BodyLimitMiddleware)

    @app.exception_handler(ValueError)
    async def invalid_tool_input(request, exc):
        return JSONResponse({"detail": "Tool input was rejected."}, status_code=422)

    @app.exception_handler(Exception)
    async def fixed_internal_failure(request, exc):
        return JSONResponse({"detail": "Tool service request failed."}, status_code=500)

    @app.middleware("http")
    async def no_store(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/tools")
    async def tools(request: Request):
        await _authorize(request, token_verifier, bindings, required_scope, default_profile)
        return tool_service.catalog_payload(cli, policy="server")

    for spec in tool_service.build_catalog(cli).values():
        if spec.policy != "server":
            continue
        model = _input_model(spec)

        def endpoint_factory(current_spec, input_model):
            async def endpoint(payload, request: Request):
                profile = await _authorize(
                    request, token_verifier, bindings, required_scope, default_profile
                )
                invocation = partial(
                    tool_service.invoke_tool,
                    current_spec.name,
                    payload.model_dump(exclude_none=True, exclude_unset=True),
                    bound_profile=profile,
                )
                return await anyio.to_thread.run_sync(
                    invocation,
                    limiter=request.app.state.tool_limiter,
                )

            endpoint.__name__ = f"call_{current_spec.name}"
            endpoint.__annotations__["payload"] = input_model
            return endpoint

        app.add_api_route(
            spec.route,
            endpoint_factory(spec, model),
            methods=["POST"],
            response_model=None,
            summary=spec.description,
        )

        if spec.read_only:
            def query_factory(current_spec, input_model):
                async def query(request: Request):
                    profile = await _authorize(request, token_verifier, bindings, required_scope, default_profile)
                    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
                        raise ValueError("Duplicate query parameters are not supported.")
                    payload = input_model.model_validate(dict(request.query_params))
                    return await anyio.to_thread.run_sync(
                        partial(tool_service.invoke_tool, current_spec.name, payload.model_dump(exclude_none=True, exclude_unset=True), bound_profile=profile),
                        limiter=request.app.state.tool_limiter,
                    )
                return query

            app.add_api_route(spec.route, query_factory(spec, model), methods=["GET"], response_model=None, summary=spec.description)

    if include_mcp:
        mcp_app = mcp_server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
            host="127.0.0.1",
            max_request_body_size=30 * 1024 * 1024,
            transport_security=TransportSecuritySettings(
                allowed_hosts=[value for host in (allowed_hosts or ["127.0.0.1", "localhost", "testserver"]) for value in (host, f"{host}:*")],
                allowed_origins=[],
            ),
        )
        app.mount("/mcp", mcp_app)
    return app


def _mcp_callable(
    spec,
    bound_profile=None,
    *,
    auth_required=False,
    profile_bindings=None,
    required_scope="chatpypi:invoke",
):
    limiter_holder = {}

    async def call(**kwargs) -> dict[str, Any]:
        profile = bound_profile
        if auth_required:
            from mcp.server.auth.middleware.auth_context import get_access_token

            access = get_access_token()
            if access is None or required_scope not in access.scopes:
                raise ValueError("Authenticated MCP scope is missing")
            profile = bound_profile_for_access(access, profile_bindings or {})
            if profile is None:
                raise ValueError("Authenticated caller has no PyPI profile binding")
        limiter = limiter_holder.get("limiter")
        if limiter is None:
            limiter = limiter_holder["limiter"] = anyio.CapacityLimiter(4)
        supplied = {key: value for key, value in kwargs.items() if value is not None}
        return await anyio.to_thread.run_sync(
            partial(tool_service.invoke_tool, spec.name, supplied, bound_profile=profile),
            limiter=limiter,
        )

    required = set(spec.input_schema.get("required", ()))
    ordered = sorted(spec.input_schema["properties"].items(), key=lambda item: item[0] not in required)
    parameters = []
    for name, field in ordered:
        default = inspect.Parameter.empty if name in required else field.get("default")
        parameters.append(
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=_python_type(field),
            )
        )
    call.__name__ = spec.name
    call.__doc__ = spec.description
    call.__signature__ = inspect.Signature(parameters, return_annotation=dict[str, Any])
    return call


def bound_profile_for_access(access, bindings):
    return bound_profile(access, bindings)


def create_mcp_server(
    *,
    token_verifier=None,
    bound_profile: str | None = None,
    profile_bindings: dict[str, str] | None = None,
    required_scope: str = "chatpypi:invoke",
) -> MCPServer:
    auth = None
    if token_verifier is not None:
        issuer = getattr(token_verifier, "issuer", None)
        if not issuer:
            raise ValueError("An authenticated MCP verifier must expose its issuer URL")
        auth = AuthSettings(
            issuer_url=issuer,
            resource_server_url=None,
            required_scopes=[required_scope],
            validate_token_resource=False,
        )
    server = MCPServer(
        name="ChatPyPI",
        description="ChatPyPI CLI capability adapter",
        version=__version__,
        token_verifier=token_verifier,
        auth=auth,
    )
    for spec in tool_service.build_catalog(cli).values():
        if spec.policy == "server":
            server.add_tool(
                _mcp_callable(
                    spec,
                    bound_profile,
                    auth_required=token_verifier is not None,
                    profile_bindings=profile_bindings,
                    required_scope=required_scope,
                ),
                name=spec.name,
                description=spec.description,
                structured_output=True,
            )
    return server


__all__ = ["create_app", "create_mcp_server"]
