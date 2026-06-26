from pathlib import Path

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


def test_env_profile_token_beats_process_env(monkeypatch):
    process_token = session_ops.encode_session_token({"username": "Process", "cookies": []})
    profile_token = session_ops.encode_session_token({"username": "Profile", "cookies": []})
    monkeypatch.setenv("PYPI_SESSION_TOKEN", process_token)
    monkeypatch.setattr(
        session_ops,
        "load_pypi_env_profile",
        lambda profile, home=None: {"PYPI_SESSION_TOKEN": profile_token},
    )

    payload = session_ops.load_session_payload_from_env(env_profile="RexWzh")

    assert payload["username"] == "Profile"


def test_build_and_reload_session_payload(tmp_path):
    session = requests.Session()
    session.cookies.set("session_id", "secret-cookie", domain="pypi.org", path="/")
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
    assert loaded["cookies"][0]["value"] == "secret-cookie"
    assert path.stat().st_mode & 0o777 == 0o600


def test_requests_session_from_payload_restores_cookie():
    payload = {
        "cookies": [
            {"name": "session_id", "value": "secret-cookie", "domain": "pypi.org", "path": "/"}
        ]
    }

    session = session_ops.requests_session_from_payload(payload)

    assert session.cookies.get("session_id", domain="pypi.org", path="/") == "secret-cookie"
