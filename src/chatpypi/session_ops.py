"""PyPI login session and logged-in management page helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import hmac
from html.parser import HTMLParser
import json
import os
from pathlib import Path
from struct import pack, unpack
import tempfile
import time
from typing import Any
from urllib.parse import urljoin

import requests

from .config import SESSION_TOKEN_ENV, load_active_pypi_env, load_pypi_env_profile


DEFAULT_BASE_URL = "https://pypi.org"


class PyPISessionError(RuntimeError):
    """Raised when a PyPI session/login/read operation fails cleanly."""


@dataclass(frozen=True)
class HtmlForm:
    """Minimal HTML form representation."""

    attrs: dict[str, str]
    inputs: list[dict[str, str]]

    @property
    def names(self) -> set[str]:
        return {item["name"] for item in self.inputs if item.get("name")}

    def hidden_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for item in self.inputs:
            name = item.get("name")
            if not name:
                continue
            if item.get("type") == "hidden":
                values[name] = item.get("value", "")
        return values


class FormParser(HTMLParser):
    """Collect form/input structure from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[HtmlForm] = []
        self._current_form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag == "form":
            self._current_form = {
                "attrs": {
                    key: attrs_dict[key]
                    for key in ("id", "method", "action", "class", "role")
                    if key in attrs_dict
                },
                "inputs": [],
            }
            return
        if tag == "input" and self._current_form is not None:
            self._current_form["inputs"].append(
                {
                    key: attrs_dict[key]
                    for key in ("type", "name", "value", "autocomplete", "placeholder")
                    if key in attrs_dict
                }
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._current_form is not None:
            self.forms.append(
                HtmlForm(
                    attrs=dict(self._current_form["attrs"]),
                    inputs=list(self._current_form["inputs"]),
                )
            )
            self._current_form = None


class TextLinkParser(HTMLParser):
    """Collect visible-ish text and links from PyPI management pages."""

    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attrs_dict = dict(attrs)
            self._current_href = attrs_dict.get("href")
            self._current_link_text = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        self.text_parts.append(text)
        if self._current_href is not None:
            self._current_link_text.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href is not None:
            self.links.append((self._current_href, " ".join(self._current_link_text).strip()))
            self._current_href = None
            self._current_link_text = []

    @property
    def text(self) -> str:
        return "\n".join(self.text_parts)


class SectionTableParser(HTMLParser):
    """Best-effort parser for rows grouped by headings."""

    def __init__(self) -> None:
        super().__init__()
        self.sections: list[tuple[str, list[list[str]]]] = []
        self._current_heading = ""
        self._collecting_heading: str | None = None
        self._heading_parts: list[str] = []
        self._in_table = False
        self._current_rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4"}:
            self._collecting_heading = tag
            self._heading_parts = []
        elif tag == "table":
            self._in_table = True
            self._current_rows = []
        elif self._in_table and tag == "tr":
            self._current_row = []
        elif self._in_table and tag in {"td", "th"}:
            self._current_cell_parts = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._collecting_heading is not None:
            self._heading_parts.append(text)
        if self._current_cell_parts is not None:
            self._current_cell_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._collecting_heading:
            self._current_heading = " ".join(self._heading_parts).strip()
            self._collecting_heading = None
            self._heading_parts = []
        elif self._in_table and tag in {"td", "th"} and self._current_cell_parts is not None:
            if self._current_row is not None:
                self._current_row.append(" ".join(self._current_cell_parts).strip())
            self._current_cell_parts = None
        elif self._in_table and tag == "tr" and self._current_row is not None:
            if any(self._current_row):
                self._current_rows.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._in_table:
            self.sections.append((self._current_heading, self._current_rows))
            self._in_table = False
            self._current_rows = []


def parse_forms(html: str) -> list[HtmlForm]:
    parser = FormParser()
    parser.feed(html)
    return parser.forms


def _find_login_form(forms: list[HtmlForm]) -> HtmlForm:
    for form in forms:
        if {"username", "password"}.issubset(form.names):
            return form
    raise PyPISessionError("Could not find PyPI login form in response.")


def _find_totp_form(forms: list[HtmlForm]) -> tuple[HtmlForm, str] | None:
    candidates = (
        "totp_value",
        "totp",
        "otp",
        "code",
        "authentication_code",
        "two_factor_code",
    )
    for form in forms:
        for name in candidates:
            if name in form.names:
                return form, name
    return None


def _form_action_url(base_url: str, form: HtmlForm, fallback_path: str) -> str:
    action = form.attrs.get("action") or fallback_path
    return urljoin(base_url, action)


def totp_now(secret: str, period: int = 30, digits: int = 6) -> str:
    """Generate a TOTP code using only the Python standard library."""

    normalized = secret.strip().replace(" ", "").upper()
    missing_padding = (-len(normalized)) % 8
    normalized += "=" * missing_padding
    key = base64.b32decode(normalized, casefold=True)
    counter = int(time.time() // period)
    digest = hmac.new(key, pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % (10**digits):0{digits}d}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _cookie_payload(cookie: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "value": item.value,
            "domain": item.domain,
            "path": item.path,
            "secure": item.secure,
            "expires": item.expires,
        }
        for item in cookie
    ]


def build_session_payload(
    session: requests.Session,
    *,
    username: str | None,
    base_url: str = DEFAULT_BASE_URL,
    csrf_token: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    payload: dict[str, Any] = {
        "version": 1,
        "provider": "pypi",
        "username": username,
        "base_url": base_url.rstrip("/"),
        "created_at": now,
        "updated_at": now,
        "cookies": _cookie_payload(session.cookies),
        "csrf": {},
        "meta": meta or {},
    }
    if csrf_token:
        payload["csrf"] = {
            "last_seen_token": csrf_token,
            "source_url": urljoin(base_url, "/account/login/"),
            "updated_at": now,
        }
    return payload


def save_session_payload(payload: dict[str, Any], session_file: Path | str) -> Path:
    """Write a payload to an explicitly provided JSON path.

    Runtime session state is env-backed; this helper is explicit-only for tests
    and deliberate operator export flows.
    """

    path = Path(session_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        os.replace(tmp_path, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp_path.unlink(missing_ok=True)
        raise
    return path


def encode_session_token(payload: dict[str, Any]) -> str:
    """Encode a PyPI web session payload for storage in env/ChatEnv."""

    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_session_token(token: str) -> dict[str, Any]:
    """Decode an env-backed PyPI web session token."""

    try:
        raw = token.strip()
        raw += "=" * ((-len(raw)) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - normalize decode errors for CLI callers.
        raise PyPISessionError("PYPI_SESSION_TOKEN is not a valid ChatPyPI session token.") from exc
    if not isinstance(payload, dict):
        raise PyPISessionError("PYPI_SESSION_TOKEN must decode to a JSON object.")
    return payload


def load_session_payload_from_env(
    *,
    token: str | None = None,
    token_env: str = SESSION_TOKEN_ENV,
    env_profile: str | None = None,
    home: str | Path | None = None,
) -> dict[str, Any]:
    """Load a session payload from explicit token, process env, or ChatEnv."""

    value = token
    if not value and env_profile:
        try:
            value = load_pypi_env_profile(env_profile, home=home).get(token_env)
        except ValueError as exc:
            raise PyPISessionError(str(exc)) from exc
    if not value and not env_profile:
        value = os.getenv(token_env)
    if not value and not env_profile:
        value = load_active_pypi_env(home).get(token_env)
    if not value:
        profile_hint = f" in profile {env_profile!r}" if env_profile else ""
        raise PyPISessionError(
            f"{token_env}{profile_hint} is missing. Run `chatpypi auth login` to refresh the PyPI session token."
        )
    return decode_session_token(value)


def load_session_payload(session_file: Path | str) -> dict[str, Any]:
    """Read a payload from an explicitly provided JSON path."""

    path = Path(session_file).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PyPISessionError(f"Session file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PyPISessionError(f"Session file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PyPISessionError(f"Session file must contain a JSON object: {path}")
    return payload


def requests_session_from_payload(payload: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        raise PyPISessionError("Session payload missing cookie list.")
    for item in cookies:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        session.cookies.set(
            str(item["name"]),
            str(item.get("value", "")),
            domain=item.get("domain") or "pypi.org",
            path=item.get("path") or "/",
        )
    return session


def _assert_logged_in_response(response: requests.Response) -> None:
    if response.status_code != 200:
        raise PyPISessionError(
            f"PyPI returned unexpected status {response.status_code} for {response.url}."
        )
    if "/account/login" in response.url:
        raise PyPISessionError("PyPI session is not logged in; redirected to login page.")
    forms = parse_forms(response.text)
    if any({"username", "password"}.issubset(form.names) for form in forms):
        raise PyPISessionError("PyPI session appears unauthenticated.")
    lowered = response.text.lower()
    logged_in_markers = (
        "account settings",
        "your projects",
        "projects with active publishers",
        "trusted publisher",
        "/account/logout/",
        "log out",
    )
    if not any(marker in lowered for marker in logged_in_markers):
        raise PyPISessionError("PyPI returned an unexpected page while validating the session.")


def validate_session_payload(
    payload: dict[str, Any], *, timeout: float = 20.0
) -> dict[str, Any]:
    base_url = str(payload.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    session = requests_session_from_payload(payload)
    response = session.get(urljoin(base_url, "/manage/account/"), timeout=timeout)
    _assert_logged_in_response(response)
    text = TextLinkParser()
    text.feed(response.text)
    return {
        "provider": payload.get("provider") or "pypi",
        "username": payload.get("username"),
        "base_url": base_url,
        "source_url": response.url,
        "authenticated": True,
        "status_code": response.status_code,
        "page_title_hint": next((part for part in text.text_parts if "Account" in part), None),
    }


def login_to_pypi(
    *,
    username: str,
    password: str,
    totp_secret: str | None = None,
    session_file: Path | str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 20.0,
) -> tuple[dict[str, Any], str]:
    base_url = base_url.rstrip("/")
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "ChatPyPI/0.2 (+https://github.com/ChatArch/ChatPyPI)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    login_url = urljoin(base_url, "/account/login/")
    login_page = session.get(login_url, timeout=timeout)
    login_form = _find_login_form(parse_forms(login_page.text))
    data = login_form.hidden_values()
    csrf_token = data.get("csrf_token")
    data.update({"username": username, "password": password})
    response = session.post(
        _form_action_url(base_url, login_form, "/account/login/"),
        data=data,
        headers={"Referer": login_url, "Origin": base_url},
        timeout=timeout,
        allow_redirects=True,
    )
    forms = parse_forms(response.text)
    totp_form = _find_totp_form(forms)
    if totp_form is not None:
        if not totp_secret:
            raise PyPISessionError(
                "PyPI login requires two-factor authentication; set PYPI_TOTP_SECRET or pass --totp-env."
            )
        form, field_name = totp_form
        totp_data = form.hidden_values()
        totp_data[field_name] = totp_now(totp_secret)
        response = session.post(
            _form_action_url(base_url, form, response.url),
            data=totp_data,
            headers={"Referer": response.url, "Origin": base_url},
            timeout=timeout,
            allow_redirects=True,
        )
    if "invalid" in response.text.lower() and "password" in response.text.lower():
        raise PyPISessionError("PyPI rejected the supplied username/password.")
    account = session.get(urljoin(base_url, "/manage/account/"), timeout=timeout)
    _assert_logged_in_response(account)
    payload = build_session_payload(
        session,
        username=username,
        base_url=base_url,
        csrf_token=csrf_token,
        meta={"login_verified_at": _utc_now()},
    )
    if session_file is not None:
        save_session_payload(payload, session_file)
    return payload, encode_session_token(payload)


def extract_project_names(html: str) -> list[str]:
    parser = TextLinkParser()
    parser.feed(html)
    names: list[str] = []
    for href, text in parser.links:
        href = href.strip()
        if href.startswith("/project/"):
            parts = [part for part in href.split("/") if part]
            if len(parts) >= 2:
                names.append(parts[1])
        elif href.startswith("/manage/project/"):
            parts = [part for part in href.split("/") if part]
            if len(parts) >= 3:
                names.append(parts[2])
        elif text and href.startswith("/manage/projects/") and text not in {"Your projects", "Projects"}:
            names.append(text)
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def list_projects_from_payload(
    payload: dict[str, Any], *, timeout: float = 20.0
) -> dict[str, Any]:
    base_url = str(payload.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    session = requests_session_from_payload(payload)
    response = session.get(urljoin(base_url, "/manage/projects/"), timeout=timeout)
    _assert_logged_in_response(response)
    projects = extract_project_names(response.text)
    return {
        "capability": "session",
        "source_url": response.url,
        "projects": projects,
        "count": len(projects),
        "empty": len(projects) == 0,
    }


def list_projects_from_session(
    session_token: str | None = None,
    *,
    token_env: str = SESSION_TOKEN_ENV,
    env_profile: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    payload = load_session_payload_from_env(
        token=session_token,
        token_env=token_env,
        env_profile=env_profile,
    )
    return list_projects_from_payload(payload, timeout=timeout)


def _table_records_for_keywords(html: str, keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    parser = SectionTableParser()
    parser.feed(html)
    records: list[dict[str, Any]] = []
    lowered_keywords = tuple(keyword.lower() for keyword in keywords)
    for heading, rows in parser.sections:
        heading_l = heading.lower()
        if "remove trusted publisher" in heading_l:
            continue
        if lowered_keywords and not any(keyword in heading_l for keyword in lowered_keywords):
            continue
        if not rows:
            continue
        headers = rows[0]
        for row in rows[1:]:
            if not any(row):
                continue
            record = {
                "section": heading,
                "values": row,
            }
            if len(headers) == len(row) and any(headers):
                record["fields"] = dict(zip(headers, row))
            records.append(record)
    return records


def parse_publishing_page(html: str) -> dict[str, Any]:
    text = TextLinkParser()
    text.feed(html)
    page_text = text.text.lower()
    active = _table_records_for_keywords(html, ("active",))
    pending = _table_records_for_keywords(html, ("pending",))
    publisher_details: list[dict[str, Any]] = []
    detail_parser = SectionTableParser()
    detail_parser.feed(html)
    for heading, rows in detail_parser.sections:
        if "remove trusted publisher" not in heading.lower() or len(rows) < 2:
            continue
        headers = rows[0]
        for row in rows[1:]:
            if not any(row):
                continue
            record: dict[str, Any] = {"section": heading, "values": row}
            if len(headers) == len(row) and any(headers):
                record["fields"] = dict(zip(headers, row))
            publisher_details.append(record)
    if "no active" in page_text and "publisher" in page_text:
        active = []
    if "no pending" in page_text and "publisher" in page_text:
        pending = []
    return {
        "active_publishers": active,
        "pending_publishers": pending,
        "publisher_details": publisher_details,
        "active_count": len(active),
        "pending_count": len(pending),
    }


def list_publishers_from_payload(
    payload: dict[str, Any], *, timeout: float = 20.0
) -> dict[str, Any]:
    base_url = str(payload.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    session = requests_session_from_payload(payload)
    response = session.get(urljoin(base_url, "/manage/account/publishing/"), timeout=timeout)
    _assert_logged_in_response(response)
    parsed = parse_publishing_page(response.text)
    parsed.update({"capability": "session", "source_url": response.url})
    return parsed


def list_publishers_from_session(
    session_token: str | None = None,
    *,
    token_env: str = SESSION_TOKEN_ENV,
    env_profile: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    payload = load_session_payload_from_env(
        token=session_token,
        token_env=token_env,
        env_profile=env_profile,
    )
    return list_publishers_from_payload(payload, timeout=timeout)


__all__ = [
    "DEFAULT_BASE_URL",
    "PyPISessionError",
    "build_session_payload",
    "decode_session_token",
    "encode_session_token",
    "extract_project_names",
    "list_projects_from_payload",
    "list_projects_from_session",
    "list_publishers_from_payload",
    "list_publishers_from_session",
    "load_session_payload",
    "load_session_payload_from_env",
    "login_to_pypi",
    "parse_forms",
    "parse_publishing_page",
    "requests_session_from_payload",
    "save_session_payload",
    "totp_now",
    "validate_session_payload",
]
