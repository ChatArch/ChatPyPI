"""Bounded terminal adapter for PyPI email confirmation links."""

from __future__ import annotations

import os
import signal
import sys
import threading
from typing import Any

from chatstyle import ask_text

from chatpypi.session_ops import (
    EmailConfirmationCancelledError,
    EmailConfirmationTimeoutError,
)


class _PromptDeadline(BaseException):
    """Internal signal escape that prompt libraries should not absorb."""


def preflight_email_confirmation_prompt() -> None:
    """Reject terminal contexts that cannot provide a safe bounded wait."""

    supported = (
        os.name == "posix"
        and threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
        and hasattr(signal, "getitimer")
        and sys.stdin.isatty()
    )
    if not supported:
        raise RuntimeError(
            "--wait-email requires a supported POSIX main-thread interactive terminal; "
            "automation should use the Python confirmation_provider API."
        )
    if signal.getsignal(signal.SIGALRM) != signal.SIG_DFL:
        raise RuntimeError("--wait-email cannot replace an existing caller SIGALRM handler.")
    delay, interval = signal.getitimer(signal.ITIMER_REAL)
    if delay > 0 or interval > 0:
        raise RuntimeError("--wait-email cannot replace an existing caller real-time alarm.")


def _terminal_state() -> tuple[int, list[Any]] | None:
    try:
        import termios

        fd = sys.stdin.fileno()
        if not os.isatty(fd):
            return None
        return fd, termios.tcgetattr(fd)
    except (AttributeError, OSError, ValueError):
        return None


def _restore_terminal_state(state: tuple[int, list[Any]] | None) -> None:
    if state is None:
        return
    try:
        import termios

        termios.tcsetattr(state[0], termios.TCSADRAIN, state[1])
    except (OSError, termios.error):
        pass


def ask_email_confirmation_url(checkpoint: object, remaining: float) -> str:
    """Read one hidden URL with a real POSIX deadline and full state cleanup."""

    del checkpoint  # The terminal prompt intentionally displays no account or token data.
    if remaining <= 0:
        raise EmailConfirmationTimeoutError()
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_handler != signal.SIG_DFL or previous_timer != (0.0, 0.0):
        raise RuntimeError("Email confirmation prompt cannot replace an existing caller alarm.")
    terminal_state = _terminal_state()

    def deadline_handler(signum, frame):
        del signum, frame
        raise _PromptDeadline()

    try:
        signal.signal(signal.SIGALRM, deadline_handler)
        signal.setitimer(signal.ITIMER_REAL, remaining)
        try:
            return ask_text("PyPI email confirmation URL", password=True)
        except _PromptDeadline:
            raise EmailConfirmationTimeoutError() from None
        except (KeyboardInterrupt, EOFError):
            raise EmailConfirmationCancelledError() from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer != (0.0, 0.0):
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        _restore_terminal_state(terminal_state)


__all__ = ["ask_email_confirmation_url", "preflight_email_confirmation_prompt"]
