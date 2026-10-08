"""Bounded HTTP client for ChatPyPI service-mode CLI dispatch."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from chatenv import TokenStore
import httpx


def validate_base_url(value: str | None) -> str:
    if not value:
        raise ValueError("CHATPYPI_BASE_URL is required in service mode.")
    invalid = False
    try:
        parsed = urlsplit(value)
        parsed.port
    except (ValueError, UnicodeError):
        invalid = True
    if invalid:
        raise ValueError("CHATPYPI_BASE_URL must be a valid HTTP(S) URL.")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ord(char) < 33 for char in value)
    ):
        raise ValueError("CHATPYPI_BASE_URL must be a valid HTTP(S) URL.")
    loopback = parsed.hostname == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(str(parsed.hostname)).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not loopback:
        raise ValueError("CHATPYPI_BASE_URL must use HTTPS except on loopback.")
    return value.rstrip("/")


def _prepare_upload(arguments: dict[str, Any]) -> dict[str, Any]:
    forbidden = {"repository_url", "username", "password_env", "token_env"}
    if any(arguments.get(name) is not None for name in forbidden):
        raise ValueError("Credential and repository URL selectors are not accepted in service mode.")
    project_dir = Path(arguments.get("project_dir") or ".").resolve()
    raw_dist = arguments.get("dist_dir")
    dist_dir = Path(raw_dist).resolve() if raw_dist else project_dir / "dist"
    if not dist_dir.is_dir():
        raise ValueError("No managed distributions were found. Run `chatpypi build` first.")
    candidates: list[Path] = []
    for pattern in ("*.whl", "*.tar.gz", "*.zip"):
        candidates.extend(dist_dir.glob(pattern))
    candidates = sorted(set(candidates))
    if not candidates:
        raise ValueError("No managed distributions were found. Run `chatpypi build` first.")
    artifacts = []
    total = 0
    for path in candidates:
        if path.is_symlink():
            raise ValueError("Distribution symbolic links are not accepted in service mode.")
        if not path.is_file() or path.parent.resolve() != dist_dir.resolve():
            raise ValueError("Distribution path is not a managed artifact.")
        size = path.stat().st_size
        if size < 1 or size > 10 * 1024 * 1024:
            raise ValueError("A distribution exceeds the 10 MiB artifact limit.")
        total += size
        if total > 20 * 1024 * 1024 or len(artifacts) >= 4:
            raise ValueError("Managed distributions exceed the upload limits.")
        content = path.read_bytes()
        artifacts.append(
            {
                "filename": path.name,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return {
        "artifacts": artifacts,
        "repository": arguments.get("repository", "pypi"),
        "skip_existing": bool(arguments.get("skip_existing", False)),
    }


def load_access_token(profile: str, *, token_env: str = "CHATPYPI_ACCESS_TOKEN") -> str | None:
    """Load an explicit bootstrap token or a ChatAuth access token."""

    explicit = os.getenv(token_env)
    if explicit:
        return explicit
    payload = TokenStore().read("ChatAuth", profile)
    values = payload.get("values") if isinstance(payload, dict) else None
    if not isinstance(values, dict):
        return None
    token = values.get("access_token")
    return str(token) if token else None


def call_remote_tool(
    *,
    base_url: str,
    spec,
    arguments: dict[str, Any],
    auth_profile: str,
    token_env: str = "CHATPYPI_ACCESS_TOKEN",
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Make exactly one non-redirecting tool request; writes are never retried."""

    url = validate_base_url(base_url) + spec.route
    if spec.name == "pkg_probe" and not arguments.get("package_name"):
        from chatpypi.main import read_project_metadata, PyPICommandError

        try:
            name = read_project_metadata(Path(arguments.get("project_dir") or ".")).name
        except PyPICommandError:
            name = None
        if not name:
            raise ValueError("Package name is required. Pass NAME or provide a local pyproject.toml.")
        arguments = {**arguments, "package_name": name}
    if spec.name == "pkg_probe":
        if arguments.get("repository_url"):
            raise ValueError("Custom repository URLs are not accepted in service mode.")
        arguments = {key: value for key, value in arguments.items() if key not in {"project_dir", "repository_url"}}
    if spec.name == "pkg_upload":
        arguments = _prepare_upload(arguments)
    token = load_access_token(auth_profile, token_env=token_env)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    failed = False
    try:
        with httpx.Client(follow_redirects=False, timeout=timeout, trust_env=False) as client:
            response = client.post(url, json=arguments, headers=headers)
    except httpx.HTTPError:
        failed = True
    if failed:
        raise ValueError("ChatPyPI service connection failed.")
    if response.is_redirect:
        raise ValueError("ChatPyPI service redirects are not allowed.")
    if len(response.content) > 1_048_576:
        raise ValueError("ChatPyPI service response exceeds the 1 MiB limit.")
    invalid = False
    try:
        payload = response.json()
    except ValueError:
        invalid = True
    if invalid:
        raise ValueError("ChatPyPI service returned a non-JSON response.")
    if response.status_code >= 400:
        messages = {
            401: "ChatPyPI service authentication failed.",
            403: "ChatPyPI service authorization failed.",
            413: "ChatPyPI service request is too large.",
            422: "ChatPyPI service rejected the tool input.",
        }
        raise ValueError(messages.get(response.status_code, "ChatPyPI service request failed."))
    if not isinstance(payload, dict) or type(payload.get("exit_code")) is not int:
        raise ValueError("ChatPyPI service returned an invalid tool result.")
    if any(not isinstance(payload.get(key, ""), str) for key in ("stdout", "stderr")):
        raise ValueError("ChatPyPI service returned an invalid tool result.")
    return payload


__all__ = ["call_remote_tool", "load_access_token", "validate_base_url"]
