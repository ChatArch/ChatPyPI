"""Small no-retry HTTP client for the ChatPyPI registration API."""

from __future__ import annotations

import json
from typing import Any, Callable
from urllib import parse as urllib_parse
from urllib import request as urllib_request


MAX_RESPONSE_BYTES = 1024 * 1024


class RegistrationAPIError(RuntimeError):
    def __init__(self, category: str, message: str, status_code: int | None = None):
        self.category = category
        self.safe_message = message
        self.status_code = status_code
        super().__init__(message)


class RegistrationAPIClient:
    """Server-to-server client; mutating requests are never retried."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str,
        timeout: float = 20.0,
        opener: Callable[..., Any] = urllib_request.urlopen,
    ):
        try:
            parsed = urllib_parse.urlsplit(base_url)
            parsed.port
        except (TypeError, ValueError):
            raise ValueError("Registration API URL must be an HTTP(S) origin.") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Registration API URL must be an HTTP(S) origin.")
        if parsed.scheme == "http" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("Plain HTTP is allowed only for a loopback service URL.")
        if not isinstance(token, str) or not token:
            raise ValueError("Registration API token is required.")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be positive.")
        self.base_url = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        self._token = token
        self.timeout = float(timeout)
        self._opener = opener

    @staticmethod
    def _remote_error(payload: object, status_code: int | None) -> RegistrationAPIError:
        category = "remote_error"
        message = "Registration API request failed."
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            error = payload["error"]
            if isinstance(error.get("category"), str):
                category = error["category"][:80]
            if isinstance(error.get("message"), str):
                message = error["message"][:240]
        return RegistrationAPIError(category, message, status_code)

    @staticmethod
    def _decode(raw: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RegistrationAPIError(
                "invalid_response", "Registration API returned invalid JSON."
            ) from None
        if not isinstance(payload, dict):
            raise RegistrationAPIError(
                "invalid_response", "Registration API returned an invalid response."
            )
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        authenticated: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            headers["Content-Type"] = "application/json"
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token}"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib_request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise RegistrationAPIError(
                        "invalid_response", "Registration API response exceeded the client limit."
                    )
                decoded = self._decode(raw)
                status_code = getattr(response, "status", 200)
                if isinstance(status_code, int) and status_code >= 400:
                    raise self._remote_error(decoded, status_code)
                return decoded
        except RegistrationAPIError:
            raise
        except Exception as exc:
            status_code = getattr(exc, "code", None)
            reader = getattr(exc, "read", None)
            if isinstance(status_code, int) and callable(reader):
                raw = reader(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise RegistrationAPIError(
                        "invalid_response",
                        "Registration API response exceeded the client limit.",
                        status_code,
                    ) from None
                try:
                    decoded: object = json.loads(raw.decode("utf-8"))
                except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
                    decoded = None
                raise self._remote_error(decoded, status_code) from None
            raise RegistrationAPIError(
                "transport", "Registration API request failed."
            ) from None

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", authenticated=False)

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/api/capabilities")

    def preflight(self, names: list[str], owner: str) -> dict[str, Any]:
        return self._request(
            "POST", "/api/preflight", payload={"names": names, "owner": owner}
        )

    def create_plan(
        self,
        distribution: str,
        *,
        owner: str,
        visibility: str = "private",
        description: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "distribution": distribution,
            "owner": owner,
            "visibility": visibility,
        }
        if description is not None:
            payload["description"] = description
        return self._request("POST", "/api/plans", payload=payload)

    def create_job(
        self,
        plan_id: str,
        confirmation: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/jobs",
            payload={"plan_id": plan_id, "confirmation": confirmation},
            idempotency_key=idempotency_key,
        )

    def list_jobs(self, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        query = urllib_parse.urlencode({"limit": limit, "offset": offset})
        return self._request("GET", f"/api/jobs?{query}")

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/api/jobs/{urllib_parse.quote(job_id, safe='')}"
        )


__all__ = ["RegistrationAPIClient", "RegistrationAPIError"]
