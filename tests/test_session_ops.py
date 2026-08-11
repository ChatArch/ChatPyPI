from pathlib import Path
import json

import pytest
import requests

from chatpypi import session_ops


def test_totp_now_matches_rfc_6238_vector(monkeypatch):
    monkeypatch.setattr(session_ops.time, "time", lambda: 59)

    assert session_ops.totp_now("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", digits=8) == "94287082"


def test_extract_project_names_from_manage_links():
    html = """
    <html><body>
      <a href="/project/demo-one/">demo-one</a>
      <a href="/manage/project/demo-two/releases/">demo-two</a>
      <a href="/project/demo-one/">duplicate</a>
    </body></html>
    """

    assert session_ops.extract_project_names(html) == ["demo-one", "demo-two"]


def test_parse_publishing_page_tables_and_empty_sections():
    html = """
    <html><body>
      <h2>Active publishers</h2>
      <table><tr><th>Provider</th><th>Repository</th></tr><tr><td>GitHub</td><td>ChatArch/ChatPyPI-Demo</td></tr></table>
      <h2>Remove trusted publisher ?</h2>
      <table><tr><th>Project</th><th>Publisher</th><th>Details</th></tr><tr><td>chatpypi-demo</td><td>GitHub</td><td>Repository: ChatArch/ChatPyPI-Demo Workflow: publish.yml</td></tr></table>
      <h2>Pending publishers</h2>
      <table><tr><th>Project</th><th>Publisher</th></tr><tr><td>pending-demo</td><td>GitHub</td></tr></table>
    </body></html>
    """

    payload = session_ops.parse_publishing_page(html)

    assert payload["active_count"] == 1
    assert payload["pending_count"] == 1
    assert payload["active_publishers"][0]["fields"]["Provider"] == "GitHub"
    assert payload["pending_publishers"][0]["fields"]["Project"] == "pending-demo"
    assert any(
        item.get("fields", {}).get("Details") == "Repository: ChatArch/ChatPyPI-Demo Workflow: publish.yml"
        for item in payload["publisher_details"]
    )


def test_parse_project_publishing_page_active_details_and_no_pending():
    html = """
    <html><body>
      <h1>Trusted Publisher Management</h1>
      <h2>Manage current publishers</h2>
      <h3>OpenID Connect publishers associated with ChatECNU</h3>
      <table>
        <tr><th>Publisher</th><th>Details</th><th>Action</th></tr>
        <tr>
          <td>GitHub</td>
          <td>Repository: ChatArch/ChatECNU Workflow: publish.yml Environment name:</td>
          <td>Remove</td>
        </tr>
      </table>
      <h2>Pending publishers</h2>
      <p>No pending publishers are currently configured.</p>
    </body></html>
    """

    payload = session_ops.parse_publishing_page(html)

    assert payload["active_count"] == 1
    assert payload["pending_count"] == 0
    detail = payload["publisher_details"][0]
    assert detail["publisher"] == "GitHub"
    assert detail["repository"] == "ChatArch/ChatECNU"
    assert detail["workflow"] == "publish.yml"
    assert detail["environment"] == "(Any)"


def test_parse_account_publishing_page_active_project_links():
    html = """
    <html><body>
      <h2>Manage publishers</h2>
      <h3>Projects with active publishers</h3>
      <table-free-layout>
        <a href="/manage/project/ChatEnv/settings/publishing/">ChatEnv</a>
        <a href="/manage/project/ChatCRS/settings/publishing/">Manage</a>
        <a href="/manage/project/ChatEnv/settings/publishing/">duplicate</a>
      </table-free-layout>
      <h3>Pending publishers</h3>
      <p>No pending publishers are currently configured.</p>
    </body></html>
    """

    payload = session_ops.parse_publishing_page(html)

    assert payload["active_count"] == 2
    assert payload["pending_count"] == 0
    assert [item["project"] for item in payload["active_publishers"]] == ["ChatEnv", "ChatCRS"]
    assert payload["active_publishers"][0]["fields"] == {"Project": "ChatEnv"}


def test_publisher_detail_matching_finds_exact_github_target():
    html = """
    <html><body>
      <h2>Manage current publishers</h2>
      <table>
        <tr><th>Publisher</th><th>Details</th></tr>
        <tr><td>GitHub</td><td>Repository: ChatArch/ChatECNU Workflow: publish.yml Environment name:</td></tr>
      </table>
    </body></html>
    """

    payload = session_ops.parse_publishing_page(html)

    assert session_ops.find_github_publisher(
        payload,
        owner="ChatArch",
        repository="ChatECNU",
        workflow="publish.yml",
        environment="",
    ) == payload["publisher_details"][0]
    assert session_ops.find_github_publisher(
        payload,
        owner="ChatArch",
        repository="OtherRepo",
        workflow="publish.yml",
        environment="",
    ) is None


def test_assert_logged_in_response_rejects_unexpected_page():
    response = requests.Response()
    response.status_code = 200
    response.url = "https://pypi.org/manage/account/"
    response._content = b"<html><title>Maintenance</title><body>try later</body></html>"

    with pytest.raises(session_ops.PyPISessionError, match="unexpected page"):
        session_ops._assert_logged_in_response(response)


def test_assert_logged_in_response_rejects_non_200():
    response = requests.Response()
    response.status_code = 500
    response.url = "https://pypi.org/manage/account/"
    response._content = b"server error"

    with pytest.raises(session_ops.PyPISessionError, match="unexpected status 500"):
        session_ops._assert_logged_in_response(response)


def test_session_token_store_roundtrip_uses_chatenv_parallel_profile(tmp_path):
    payload = {
        "provider": "pypi",
        "username": "Profile",
        "base_url": "https://pypi.org",
        "cookies": [{"name": "session_id", "value": "opaque-cookie-fixture", "domain": "pypi.org", "path": "/"}],
        "csrf": {"last_seen_token": "opaque-csrf-fixture"},
        "created_at": "2026-08-11T12:00:00Z",
        "updated_at": "2026-08-11T12:00:00Z",
        "meta": {"email_verified": True, "two_factor_enabled": True},
    }

    status = session_ops.save_session_payload_to_token_store(
        payload,
        env_profile="RexWzh",
        home=tmp_path / "home",
        source="test",
    )
    token_file = Path(status["token_file"])
    raw = json.loads(token_file.read_text(encoding="utf-8"))

    assert token_file == tmp_path / "home" / "tokens" / "PyPI" / "RexWzh.json"
    assert raw["service"] == "PyPI"
    assert raw["profile"] == "RexWzh"
    assert raw["token_type"] == "web_session"
    assert raw["values"]["payload"]["cookies"][0]["value"] == "opaque-cookie-fixture"
    assert raw["summary"] == {
        "provider": "pypi",
        "username": "Profile",
        "base_url": "https://pypi.org",
        "cookie_count": 1,
        "has_last_seen_csrf": True,
        "email_verified": True,
        "two_factor_enabled": True,
    }

    loaded = session_ops.load_session_payload_from_env(env_profile="RexWzh", home=tmp_path / "home")

    assert loaded["username"] == "Profile"
    assert loaded["cookies"][0]["value"] == "opaque-cookie-fixture"


def test_session_loader_does_not_fallback_to_legacy_process_env(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "PYPI_SESSION_TOKEN",
        session_ops.encode_session_token({"username": "Legacy", "cookies": []}),
    )

    with pytest.raises(session_ops.PyPISessionError, match="tokens/PyPI/default.json"):
        session_ops.load_session_payload_from_env(home=tmp_path / "home")


def test_build_and_reload_session_payload(tmp_path):
    session = requests.Session()
    session.cookies.set("session_id", "opaque-cookie-fixture", domain="pypi.org", path="/")
    payload = session_ops.build_session_payload(
        session,
        username="LooKeng",
        csrf_token="csrf",
        meta={"email_verified": True},
    )
    path = session_ops.save_session_payload(payload, tmp_path / "session.json")

    loaded = session_ops.load_session_payload(path)

    assert loaded["username"] == "LooKeng"
    assert loaded["cookies"][0]["name"] == "session_id"
    assert loaded["cookies"][0]["value"] == "opaque-cookie-fixture"


def test_requests_session_from_payload_restores_cookie():
    payload = {
        "cookies": [
            {"name": "session_id", "value": "opaque-cookie-fixture", "domain": "pypi.org", "path": "/"}
        ]
    }

    session = session_ops.requests_session_from_payload(payload)

    assert session.cookies.get("session_id", domain="pypi.org", path="/") == "opaque-cookie-fixture"
