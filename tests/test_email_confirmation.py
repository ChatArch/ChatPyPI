from __future__ import annotations

import math
import signal
import time
from urllib.parse import urlsplit

from click.testing import CliRunner
import pytest
import requests

from chatpypi import session_ops
from chatpypi.cli import cli


LOGIN_HTML = """
<form action="/account/login/" method="post">
  <input type="hidden" name="csrf_token" value="csrf-fixture">
  <input name="username"><input name="password" type="password">
</form>
"""
CHECKPOINT_HTML = "<html><body>Check your email to confirm this login.</body></html>"
TOTP_HTML = """
<form action="/account/two-factor/" method="post">
  <input type="hidden" name="csrf_token" value="totp-csrf-fixture">
  <input name="totp_value">
</form>
"""


def response(url: str, text: str, status: int = 200, **headers: str) -> requests.Response:
    item = requests.Response()
    item.status_code = status
    item.url = url
    item._content = text.encode()
    item.headers.update(headers)
    return item


def account_html(username: str) -> str:
    return f"""
    <html><body>
      <h1>Account settings</h1>
      <a href="/user/misleading-profile/">Unrelated profile</a>
      <form><input name="username" value="misleading-input" readonly></form>
      <section id="account-details">
        <h2 class="sub-title">Account details</h2>
        <div class="form-group">
          <span class="form-group__label">Username</span>
          <p class="form-group__text">{username}</p>
          <span class="form-group__label">Date Joined</span>
          <p class="form-group__text">January 1, 2020</p>
        </div>
      </section>
      <a href="/account/logout/">Log out</a>
    </body></html>
    """


class FakeSession:
    instances: list["FakeSession"] = []

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[tuple[str, str, dict]] = []
        self.headers: dict[str, str] = {}
        self.proxies: dict[str, str] = {}
        self.trust_env = True
        self.cookies = requests.cookies.RequestsCookieJar()
        self.__class__.instances.append(self)

    def _request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def get(self, url: str, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self._request("POST", url, **kwargs)


def install_session(monkeypatch, replies):
    fake = FakeSession(replies)
    monkeypatch.setattr(session_ops.requests, "Session", lambda: fake)
    monkeypatch.setattr(session_ops.requests.utils, "get_environ_proxies", lambda url: {"https": "http://proxy.test"})
    return fake


def checkpoint_replies(actual_username: str = "alice"):
    return [
        response("https://pypi.org/account/login/", LOGIN_HTML),
        response("https://pypi.org/account/confirm-login/", CHECKPOINT_HTML),
        response("https://pypi.org/manage/account/", account_html(actual_username)),
        response("https://pypi.org/manage/account/", account_html(actual_username)),
    ]


def assert_clean_exception_chain(exc: BaseException, secret: str) -> None:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        assert secret not in str(current)
        current = current.__cause__ or current.__context__


def test_ordinary_login_keeps_shape_and_uses_actual_account_username(monkeypatch):
    fake = install_session(
        monkeypatch,
        [
            response("https://pypi.org/account/login/", LOGIN_HTML),
            response("https://pypi.org/manage/account/", account_html("alice")),
            response("https://pypi.org/manage/account/", account_html("alice")),
        ],
    )

    payload, token = session_ops.login_to_pypi(username="alice", password="password-fixture")

    assert payload["username"] == "alice"
    assert payload["meta"]["login_verified_at"]
    assert isinstance(token, str) and token
    assert len(FakeSession.instances[-1].calls) == 3
    assert fake.trust_env is False
    assert fake.proxies == {"https": "http://proxy.test"}


def test_account_identity_uses_official_account_details_field_only():
    item = response("https://pypi.org/manage/account/", account_html("CanonicalUser"))

    assert session_ops._authenticated_account_username(item) == "CanonicalUser"


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><a href='/user/alice/'>Alice</a><input name='username' value='alice'></body></html>",
        """
        <section id="account-details">
          <div class="form-group">
            <span class="form-group__label">Full name</span>
            <p class="form-group__text">Alice Example</p>
          </div>
        </section>
        """,
        """
        <section id="account-details">
          <div class="form-group">
            <span class="form-group__label">Username</span><p class="form-group__text">alice</p>
            <span class="form-group__label">Username</span><p class="form-group__text">mallory</p>
          </div>
        </section>
        """,
    ],
)
def test_account_identity_missing_or_ambiguous_fails_closed(html):
    item = response("https://pypi.org/manage/account/", html)

    with pytest.raises(session_ops.PyPIAuthenticationError, match="account identity"):
        session_ops._authenticated_account_username(item)


def test_login_accepts_ascii_case_canonicalization_and_preserves_server_username(monkeypatch):
    install_session(
        monkeypatch,
        [
            response("https://pypi.org/account/login/", LOGIN_HTML),
            response("https://pypi.org/manage/account/", account_html("CanonicalUser")),
            response("https://pypi.org/manage/account/", account_html("CanonicalUser")),
        ],
    )

    payload, _ = session_ops.login_to_pypi(
        username="canonicaluser",
        password="password-fixture",
    )

    assert payload["username"] == "CanonicalUser"


def test_checkpoint_without_provider_is_specific_required_error(monkeypatch):
    install_session(monkeypatch, checkpoint_replies()[:2])

    with pytest.raises(session_ops.EmailConfirmationRequiredError) as caught:
        session_ops.login_to_pypi(username="alice", password="password-fixture")

    assert caught.value.category == "confirmation_required"
    assert "confirmation" in str(caught.value).lower()


def test_confirmation_success_reuses_session_and_verifies_actual_username(monkeypatch):
    fake = install_session(monkeypatch, checkpoint_replies())
    descriptors = []

    def provider(checkpoint, remaining):
        descriptors.append((checkpoint, remaining))
        return "https://pypi.org/account/confirm-login/?token=opaque-fixture"

    payload, _ = session_ops.login_to_pypi(
        username="alice",
        password="password-fixture",
        confirmation_provider=provider,
        confirmation_timeout=30,
    )

    assert payload["username"] == "alice"
    assert len(FakeSession.instances) >= 1
    assert [call[0] for call in fake.calls] == ["GET", "POST", "GET", "GET"]
    confirmation_call = fake.calls[2]
    assert urlsplit(confirmation_call[1]).query == "token=opaque-fixture"
    assert "Referer" not in confirmation_call[2].get("headers", {})
    checkpoint, remaining = descriptors[0]
    assert checkpoint.origin == "https://pypi.org"
    assert checkpoint.path == "/account/confirm-login/"
    assert "token" not in repr(checkpoint).lower()
    assert 0 < remaining <= 30


def test_confirmation_rejects_wrong_authenticated_account(monkeypatch):
    install_session(monkeypatch, checkpoint_replies(actual_username="mallory"))

    with pytest.raises(session_ops.PyPIAuthenticationError, match="account identity") as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=lambda checkpoint, remaining: (
                "https://pypi.org/account/confirm-login/?token=opaque-fixture"
            ),
            confirmation_timeout=30,
        )

    assert caught.value.category == "authentication"


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://pypi.org/account/confirm-login/?token=x",
        "https://test.pypi.org/account/confirm-login/?token=x",
        "https://user@pypi.org/account/confirm-login/?token=x",
        "https://pypi.org:443/account/confirm-login/?token=x",
        "https://pypi.org/account/confirm-login?token=x",
        "https://pypi.org/account/confirm-login/?token=",
        "https://pypi.org/account/confirm-login/?token=x&next=https://evil.test",
        "https://pypi.org/account/confirm-login/?token=x;next=https://evil.test",
        "https://pypi.org/account/confirm-login/?token=x#fragment",
        "https://pypi.org/account/confirm-login/?token=x\n",
        "https://pypi.org\\@evil.test/account/confirm-login/?token=x",
    ],
)
def test_confirmation_url_adversaries_are_rejected_before_request(monkeypatch, bad_url):
    fake = install_session(monkeypatch, checkpoint_replies()[:2])

    with pytest.raises(session_ops.InvalidEmailConfirmationError) as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=lambda checkpoint, remaining: bad_url,
            confirmation_timeout=30,
        )

    assert caught.value.category == "invalid_confirmation"
    assert len(fake.calls) == 2
    assert bad_url not in str(caught.value)


def test_confirmation_redirect_cannot_exfiltrate_token(monkeypatch):
    secret_url = "https://pypi.org/account/confirm-login/?token=opaque-fixture"
    fake = install_session(
        monkeypatch,
        [
            *checkpoint_replies()[:2],
            response(secret_url, "", 302, Location="https://evil.test/collect"),
        ],
    )

    with pytest.raises(session_ops.InvalidEmailConfirmationError) as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=lambda checkpoint, remaining: secret_url,
            confirmation_timeout=30,
        )

    assert len(fake.calls) == 3
    assert all("evil.test" not in call[1] for call in fake.calls)
    assert_clean_exception_chain(caught.value, "opaque-fixture")


def test_confirmation_success_redirect_has_no_token_referer(monkeypatch):
    secret_url = "https://pypi.org/account/confirm-login/?token=opaque-fixture"
    fake = install_session(
        monkeypatch,
        [
            *checkpoint_replies()[:2],
            response(secret_url, "", 302, Location="/manage/account/"),
            response("https://pypi.org/manage/account/", account_html("alice")),
            response("https://pypi.org/manage/account/", account_html("alice")),
        ],
    )

    payload, _ = session_ops.login_to_pypi(
        username="alice",
        password="password-fixture",
        confirmation_provider=lambda checkpoint, remaining: secret_url,
        confirmation_timeout=30,
    )

    assert payload["username"] == "alice"
    redirected_call = fake.calls[3]
    assert redirected_call[1] == "https://pypi.org/manage/account/"
    assert redirected_call[2].get("headers") == {}
    assert "opaque-fixture" not in repr(redirected_call[2])


def test_confirmation_token_never_enters_downstream_totp_headers_or_exception_chain(monkeypatch):
    canary = "confirmation-canary"
    secret_url = f"https://pypi.org/account/confirm-login/?token={canary}"
    totp_url = f"https://pypi.org/account/two-factor/?token={canary}"
    fake = install_session(
        monkeypatch,
        [
            *checkpoint_replies()[:2],
            response(secret_url, "", 302, Location=f"/account/two-factor/?token={canary}"),
            response(totp_url, TOTP_HTML),
            requests.ConnectionError(f"network failure retained {canary}"),
        ],
    )
    monkeypatch.setattr(session_ops, "totp_now", lambda secret: "123456")

    with pytest.raises(session_ops.PyPINetworkError) as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            totp_secret="totp-seed-fixture",
            confirmation_provider=lambda checkpoint, remaining: secret_url,
            confirmation_timeout=30,
        )

    downstream_headers = [call[2].get("headers", {}) for call in fake.calls[2:]]
    assert all(canary not in repr(headers) for headers in downstream_headers)
    totp_post = fake.calls[-1]
    assert totp_post[0] == "POST"
    assert totp_post[1] == "https://pypi.org/account/two-factor/"
    assert totp_post[2]["headers"]["Referer"] == "https://pypi.org/account/two-factor/"
    assert_clean_exception_chain(caught.value, canary)


def test_totp_then_email_checkpoint_keeps_normal_two_factor_flow(monkeypatch):
    fake = install_session(
        monkeypatch,
        [
            response("https://pypi.org/account/login/", LOGIN_HTML),
            response("https://pypi.org/account/two-factor/", TOTP_HTML),
            response("https://pypi.org/account/confirm-login/", CHECKPOINT_HTML),
            response("https://pypi.org/manage/account/", account_html("alice")),
            response("https://pypi.org/manage/account/", account_html("alice")),
        ],
    )
    monkeypatch.setattr(session_ops, "totp_now", lambda secret: "123456")

    payload, _ = session_ops.login_to_pypi(
        username="alice",
        password="password-fixture",
        totp_secret="totp-seed-fixture",
        confirmation_provider=lambda checkpoint, remaining: (
            "https://pypi.org/account/confirm-login/?token=opaque-fixture"
        ),
        confirmation_timeout=30,
    )

    assert payload["username"] == "alice"
    assert fake.calls[2][0] == "POST"
    assert fake.calls[2][2]["data"]["totp_value"] == "123456"
    assert fake.calls[3][0] == "GET"


def test_expired_confirmation_is_distinguishable(monkeypatch):
    fake = install_session(
        monkeypatch,
        [
            *checkpoint_replies()[:2],
            response("https://pypi.org/account/confirm-login/", "Confirmation link expired."),
        ],
    )

    with pytest.raises(session_ops.InvalidEmailConfirmationError, match="expired or invalid") as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=lambda checkpoint, remaining: (
                "https://pypi.org/account/confirm-login/?token=expired-fixture"
            ),
            confirmation_timeout=30,
        )

    assert caught.value.category == "invalid_confirmation"
    assert len(fake.calls) == 3


def test_provider_timeout_before_and_after_callback(monkeypatch):
    install_session(monkeypatch, checkpoint_replies()[:2])
    clock = iter([100.0, 100.0, 131.0])
    monkeypatch.setattr(session_ops.time, "monotonic", lambda: next(clock))

    with pytest.raises(session_ops.EmailConfirmationTimeoutError) as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=lambda checkpoint, remaining: (
                "https://pypi.org/account/confirm-login/?token=opaque-fixture"
            ),
            confirmation_timeout=30,
        )

    assert caught.value.category == "confirmation_timeout"


def test_provider_timeout_exception_is_sanitized(monkeypatch):
    secret = "opaque-fixture"
    install_session(monkeypatch, checkpoint_replies()[:2])

    def provider(checkpoint, remaining):
        raise TimeoutError(f"provider retained {secret}")

    with pytest.raises(session_ops.EmailConfirmationTimeoutError) as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=provider,
            confirmation_timeout=30,
        )

    assert_clean_exception_chain(caught.value, secret)


@pytest.mark.parametrize("provider_error", [KeyboardInterrupt(), EOFError()])
def test_provider_interrupt_and_eof_are_safe_cancel(monkeypatch, provider_error):
    install_session(monkeypatch, checkpoint_replies()[:2])

    def cancel(checkpoint, remaining):
        raise provider_error

    with pytest.raises(session_ops.EmailConfirmationCancelledError) as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=cancel,
            confirmation_timeout=30,
        )

    assert caught.value.category == "confirmation_cancelled"


def test_network_exception_and_chains_do_not_retain_confirmation_url(monkeypatch):
    secret = "opaque-fixture"
    secret_url = f"https://pypi.org/account/confirm-login/?token={secret}"
    install_session(
        monkeypatch,
        [*checkpoint_replies()[:2], requests.ConnectionError(f"failed GET {secret_url}")],
    )

    with pytest.raises(session_ops.PyPINetworkError) as caught:
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=lambda checkpoint, remaining: secret_url,
            confirmation_timeout=30,
        )

    assert caught.value.category == "network"
    assert_clean_exception_chain(caught.value, secret)


@pytest.mark.parametrize("value", [0, -1, math.inf, -math.inf, math.nan])
def test_api_confirmation_timeout_must_be_positive_finite(monkeypatch, value):
    called = False

    def forbidden_session():
        nonlocal called
        called = True
        raise AssertionError("network must not start")

    monkeypatch.setattr(session_ops.requests, "Session", forbidden_session)
    with pytest.raises(ValueError, match="positive finite"):
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            confirmation_provider=lambda checkpoint, remaining: "unused",
            confirmation_timeout=value,
        )
    assert called is False


@pytest.mark.parametrize("value", [0, -1, math.inf, -math.inf, math.nan, None])
def test_api_http_timeout_must_be_positive_finite_before_session(monkeypatch, value):
    called = False
    secret = "timeout-secret-canary"

    def forbidden_session():
        nonlocal called
        called = True
        raise AssertionError("session must not be created")

    monkeypatch.setattr(session_ops.requests, "Session", forbidden_session)
    with pytest.raises(ValueError, match="timeout must be a positive finite") as caught:
        session_ops.login_to_pypi(
            username="alice",
            password=secret,
            timeout=value,
        )
    assert called is False
    assert_clean_exception_chain(caught.value, secret)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://pypi.org",
        "https://evil.test",
        "https://pypi.org:443",
        "https://user@pypi.org",
        "https://pypi.org/path",
        "https://pypi.org////",
    ],
)
def test_api_wait_rejects_untrusted_base_before_session_creation(monkeypatch, base_url):
    called = False

    def forbidden_session():
        nonlocal called
        called = True
        raise AssertionError("network session must not be created")

    monkeypatch.setattr(session_ops.requests, "Session", forbidden_session)
    with pytest.raises(ValueError, match="trusted PyPI|https://pypi.org"):
        session_ops.login_to_pypi(
            username="alice",
            password="password-fixture",
            base_url=base_url,
            confirmation_provider=lambda checkpoint, remaining: "unused",
        )
    assert called is False


def test_plain_login_retains_custom_origin_with_port(monkeypatch):
    fake = install_session(
        monkeypatch,
        [
            response("http://localhost:8080/account/login/", LOGIN_HTML),
            response("http://localhost:8080/manage/account/", account_html("alice")),
            response("http://localhost:8080/manage/account/", account_html("alice")),
        ],
    )

    payload, _ = session_ops.login_to_pypi(
        username="alice",
        password="password-fixture",
        base_url="http://localhost:8080",
    )

    assert payload["base_url"] == "http://localhost:8080"
    assert fake.calls[0][1] == "http://localhost:8080/account/login/"


def test_cli_wait_preflight_happens_before_profile_credentials_and_network(monkeypatch):
    profile_loaded = False
    login_called = False

    def load_profile(profile):
        nonlocal profile_loaded
        profile_loaded = True
        return {"PYPI_USERNAME": "alice", "PYPI_PASSWORD": "secret"}

    def login(**kwargs):
        nonlocal login_called
        login_called = True

    monkeypatch.setattr("chatpypi.cli.load_pypi_env_profile", load_profile)
    monkeypatch.setattr("chatpypi.cli.login_to_pypi", login)

    result = CliRunner().invoke(cli, ["auth", "login", "-e", "PROFILE", "--wait-email"])

    assert result.exit_code != 0
    assert "interactive terminal" in result.output.lower()
    assert profile_loaded is False
    assert login_called is False


def test_cli_wait_rejects_untrusted_base_before_profile_credentials(monkeypatch):
    monkeypatch.setattr(
        "chatpypi.cli.load_pypi_env_profile",
        lambda profile: pytest.fail("credentials must not be loaded"),
    )
    result = CliRunner().invoke(
        cli,
        ["auth", "login", "-e", "PROFILE", "--wait-email", "--base-url", "https://evil.test"],
    )
    assert result.exit_code != 0
    assert "https://pypi.org" in result.output


@pytest.mark.parametrize("value", ["0", "-1", "inf", "nan"])
def test_cli_wait_timeout_rejects_non_positive_or_non_finite_before_credentials(monkeypatch, value):
    monkeypatch.setattr(
        "chatpypi.cli.load_pypi_env_profile",
        lambda profile: pytest.fail("credentials must not be loaded"),
    )
    result = CliRunner().invoke(
        cli,
        ["auth", "login", "-e", "PROFILE", "--wait-email", "--wait-timeout", value],
    )
    assert result.exit_code != 0
    assert "positive finite" in result.output.lower()


@pytest.mark.parametrize("value", ["0", "-1", "inf", "-inf", "nan"])
def test_cli_http_timeout_rejects_non_positive_or_non_finite_before_credentials(monkeypatch, value):
    monkeypatch.setattr(
        "chatpypi.cli.load_pypi_env_profile",
        lambda profile: pytest.fail("credentials must not be loaded"),
    )
    result = CliRunner().invoke(
        cli,
        ["auth", "login", "-e", "PROFILE", "--timeout", value],
    )
    assert result.exit_code != 0
    assert "--timeout must be a positive finite" in result.output.lower()


def test_cli_rejects_explicit_wait_timeout_without_wait_flag_before_credentials(monkeypatch):
    monkeypatch.setattr(
        "chatpypi.cli.load_pypi_env_profile",
        lambda profile: pytest.fail("credentials must not be loaded"),
    )
    result = CliRunner().invoke(
        cli,
        ["auth", "login", "-e", "PROFILE", "--wait-timeout", "10"],
    )
    assert result.exit_code != 0
    assert "requires --wait-email" in result.output


def test_cli_failure_never_writes_selected_token_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("chatpypi.cli.preflight_email_confirmation_prompt", lambda: None)
    monkeypatch.setattr(
        "chatpypi.cli.load_pypi_env_profile",
        lambda profile: {"PYPI_USERNAME": "alice", "PYPI_PASSWORD": "password-fixture"},
    )
    monkeypatch.setattr(
        "chatpypi.cli.login_to_pypi",
        lambda **kwargs: (_ for _ in ()).throw(session_ops.EmailConfirmationTimeoutError()),
    )

    result = CliRunner().invoke(
        cli,
        ["auth", "login", "-e", "PROFILE", "--wait-email", "--format", "json"],
    )

    assert result.exit_code != 0
    assert not (tmp_path / "home" / "tokens" / "PyPI" / "PROFILE.json").exists()
    assert result.stdout == ""
    assert "opaque" not in result.stderr


def test_cli_failure_does_not_replace_existing_selected_token_profile(monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("CHATARCH_HOME", str(home))
    session_ops.save_session_payload_to_token_store(
        {
            "provider": "pypi",
            "username": "previous-account",
            "base_url": "https://pypi.org",
            "cookies": [],
        },
        env_profile="PROFILE",
        home=home,
        source="test-fixture",
    )
    token_path = home / "tokens" / "PyPI" / "PROFILE.json"
    before = token_path.read_bytes()
    monkeypatch.setattr("chatpypi.cli.preflight_email_confirmation_prompt", lambda: None)
    monkeypatch.setattr(
        "chatpypi.cli.load_pypi_env_profile",
        lambda profile: {"PYPI_USERNAME": "alice", "PYPI_PASSWORD": "password-fixture"},
    )
    monkeypatch.setattr(
        "chatpypi.cli.login_to_pypi",
        lambda **kwargs: (_ for _ in ()).throw(session_ops.InvalidEmailConfirmationError()),
    )

    result = CliRunner().invoke(
        cli,
        ["auth", "login", "-e", "PROFILE", "--wait-email"],
    )

    assert result.exit_code != 0
    assert token_path.read_bytes() == before


def test_cli_json_stdout_stays_valid_and_prompt_provider_is_injected(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("chatpypi.cli.preflight_email_confirmation_prompt", lambda: None)
    monkeypatch.setattr(
        "chatpypi.cli.load_pypi_env_profile",
        lambda profile: {"PYPI_USERNAME": "alice", "PYPI_PASSWORD": "password-fixture"},
    )
    captured = {}

    def fake_login(**kwargs):
        captured.update(kwargs)
        payload = {
            "provider": "pypi",
            "username": "alice",
            "base_url": "https://pypi.org",
            "cookies": [],
            "csrf": {},
            "meta": {},
        }
        return payload, "encoded-fixture"

    monkeypatch.setattr("chatpypi.cli.login_to_pypi", fake_login)
    result = CliRunner().invoke(
        cli,
        ["auth", "login", "-e", "PROFILE", "--wait-email", "--no-write-token", "--format", "json"],
    )

    assert result.exit_code == 0
    assert result.stdout.strip().startswith("{") and result.stdout.strip().endswith("}")
    assert captured["confirmation_timeout"] == 600.0
    assert callable(captured["confirmation_provider"])


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX interval timers required")
def test_terminal_prompt_deadline_restores_alarm_and_does_not_spawn_workers(monkeypatch):
    from chatpypi import prompt_ops

    original_handler = signal.getsignal(signal.SIGALRM)
    original_timer = signal.getitimer(signal.ITIMER_REAL)
    captured = {}

    def blocking_prompt(*args, **kwargs):
        captured.update({"args": args, "kwargs": kwargs})
        return signal.pause()

    monkeypatch.setattr(prompt_ops, "ask_text", blocking_prompt)
    started = time.monotonic()

    with pytest.raises(session_ops.EmailConfirmationTimeoutError):
        prompt_ops.ask_email_confirmation_url(object(), 0.05)

    assert time.monotonic() - started < 1
    assert captured["kwargs"]["password"] is True
    assert signal.getsignal(signal.SIGALRM) == original_handler
    assert signal.getitimer(signal.ITIMER_REAL) == original_timer


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX interval timers required")
def test_terminal_prompt_eof_is_cancelled_and_restores_alarm(monkeypatch):
    from chatpypi import prompt_ops

    original_handler = signal.getsignal(signal.SIGALRM)
    original_timer = signal.getitimer(signal.ITIMER_REAL)
    monkeypatch.setattr(
        prompt_ops,
        "ask_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(EOFError()),
    )

    with pytest.raises(session_ops.EmailConfirmationCancelledError):
        prompt_ops.ask_email_confirmation_url(object(), 1)

    assert signal.getsignal(signal.SIGALRM) == original_handler
    assert signal.getitimer(signal.ITIMER_REAL) == original_timer


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX interval timers required")
def test_terminal_preflight_rejects_existing_caller_alarm(monkeypatch):
    from chatpypi import prompt_ops

    monkeypatch.setattr(prompt_ops.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(prompt_ops.signal, "getitimer", lambda timer: (2.0, 0.0))

    with pytest.raises(RuntimeError, match="existing caller real-time alarm"):
        prompt_ops.preflight_email_confirmation_prompt()
