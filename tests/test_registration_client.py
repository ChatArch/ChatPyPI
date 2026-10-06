from __future__ import annotations

import io
import json

import pytest

from chatpypi.client import RegistrationAPIClient, RegistrationAPIError


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount: int = -1) -> bytes:
        return self.payload if amount < 0 else self.payload[:amount]


def test_client_sends_bearer_and_idempotency_without_retries():
    calls = []

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse({"id": "job-1", "status": "queued"}, status=202)

    client = RegistrationAPIClient(
        "https://packages.example.internal",
        token="opaque-test-token",
        timeout=3.0,
        opener=opener,
    )
    result = client.create_job(
        "plan-1", "register:demo", idempotency_key="idem-client-0001"
    )

    assert result["id"] == "job-1"
    assert len(calls) == 1
    request, timeout = calls[0]
    assert timeout == 3.0
    assert request.get_header("Authorization") == "Bearer opaque-test-token"
    assert request.get_header("Idempotency-key") == "idem-client-0001"
    assert json.loads(request.data) == {
        "plan_id": "plan-1",
        "confirmation": "register:demo",
    }


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/socket",
        "http://packages.example.internal",
        "https://user:password@packages.example.internal",
        "https://packages.example.internal/path?token=value",
    ],
)
def test_client_rejects_unsafe_service_urls(url):
    with pytest.raises(ValueError):
        RegistrationAPIClient(url, token="opaque-test-token")


def test_client_raises_only_fixed_remote_error_fields():
    class HTTPFailure(Exception):
        code = 409

        def read(self, amount=-1):
            return json.dumps(
                {
                    "error": {
                        "category": "target_busy",
                        "message": "A registration job already owns this normalized name.",
                        "debug": "/private/server/path",
                    }
                }
            ).encode()

    def opener(_request, timeout):
        del timeout
        raise HTTPFailure()

    client = RegistrationAPIClient(
        "https://packages.example.internal", token="opaque-test-token", opener=opener
    )
    with pytest.raises(RegistrationAPIError) as exc_info:
        client.get_job("job-1")
    assert exc_info.value.category == "target_busy"
    assert exc_info.value.status_code == 409
    assert "/private" not in str(exc_info.value)
