"""Optional ChatAuth-issued RS256 access-token verification."""

from __future__ import annotations

import ipaddress
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
import anyio
import jwt
from mcp.server.auth.provider import AccessToken


def _validate_https_endpoint(value: str, label: str) -> str:
    try:
        parsed = urlsplit(value)
        parsed.port
    except (ValueError, UnicodeError):
        raise ValueError(f"{label} must be a valid HTTP(S) URL") from None
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(str(parsed.hostname)).is_loopback
    except ValueError:
        pass
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.scheme != "https" and not loopback)
    ):
        raise ValueError(f"{label} must use HTTPS except on loopback")
    return value


class JWTResourceVerifier:
    """Verify an existing issuer's RS256 JWTs; this package never issues tokens."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        required_scope: str = "chatpypi:invoke",
        jwks_url: str | None = None,
        jwks_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if not issuer or not audience or not (jwks_url or jwks_provider):
            raise ValueError("issuer, audience, and a JWKS source are required")
        self.issuer = _validate_https_endpoint(issuer, "issuer").rstrip("/")
        self.audience = audience
        self.required_scope = required_scope
        self.jwks_url = _validate_https_endpoint(jwks_url, "JWKS URL") if jwks_url else None
        self.jwks_provider = jwks_provider

    def _jwks(self) -> dict[str, Any]:
        if self.jwks_provider is not None:
            return self.jwks_provider()
        parsed = urlsplit(str(self.jwks_url))
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("JWKS URL must use HTTPS except on loopback")
        with httpx.Client(follow_redirects=False, timeout=5.0, trust_env=False) as client:
            response = client.get(str(self.jwks_url), headers={"Accept": "application/json"})
        if response.is_redirect or response.status_code != 200 or len(response.content) > 262_144:
            raise ValueError("JWKS response was rejected")
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
            raise ValueError("JWKS document is invalid")
        return data

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not header.get("kid"):
                return None
            jwks = await anyio.to_thread.run_sync(self._jwks)
            keys = jwks.get("keys", [])
            jwk = next(item for item in keys if item.get("kid") == header["kid"])
            key = jwt.PyJWK.from_dict(jwk).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
            raw_scopes = claims.get("scope", "")
            scopes = raw_scopes.split() if isinstance(raw_scopes, str) else list(raw_scopes)
            subject = claims.get("sub")
            client_id = claims.get("client_id") or claims.get("azp")
            if self.required_scope not in scopes or not (subject or client_id):
                return None
            return AccessToken(
                token=token,
                client_id=str(client_id or subject),
                subject=str(subject) if subject else None,
                scopes=[str(scope) for scope in scopes],
                expires_at=int(claims["exp"]),
                resource=self.audience,
                claims=claims,
            )
        except (jwt.PyJWTError, KeyError, StopIteration, TypeError, ValueError, httpx.HTTPError):
            return None


def bound_profile(access: Any, bindings: dict[str, str]) -> str | None:
    """Resolve only server-owned subject/client bindings."""

    subject = getattr(access, "subject", None)
    client = getattr(access, "client_id", None)
    return bindings.get(str(subject)) if subject is not None and str(subject) in bindings else bindings.get(str(client))


__all__ = ["JWTResourceVerifier", "bound_profile"]
