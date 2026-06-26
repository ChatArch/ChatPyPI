"""ChatPyPI provider configuration helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chatenv.fields import BaseEnvConfig as _BaseEnvConfig, EnvField as _EnvField
from chatenv.paths import get_paths
from chatenv.store import EnvStore

BaseEnvConfig: Any = _BaseEnvConfig
EnvField: Any = _EnvField

SESSION_TOKEN_ENV = "PYPI_SESSION_TOKEN"


class PyPIConfig(BaseEnvConfig):
    """PyPI account/session configuration for ChatPyPI."""

    _title = "PyPI Configuration"
    _aliases = ["pypi", "chatpypi"]
    _storage_dir = "PyPI"

    @classmethod
    def test(cls) -> None:
        """Validate schema registration without touching PyPI or secrets."""

        print(f"Testing {cls._title}...")
        print("Schema loaded; no network test is required.")


def load_active_pypi_env(home: str | Path | None = None) -> dict[str, str]:
    """Load active PyPI typed env values from ChatEnv/ChatArch home."""

    return EnvStore(get_paths(home).envs_dir).load_active(PyPIConfig)


def load_pypi_env_profile(
    profile_name: str,
    *,
    home: str | Path | None = None,
) -> dict[str, str]:
    """Load a named PyPI ChatEnv profile without activating it globally."""

    return EnvStore(get_paths(home).envs_dir).load_profile(PyPIConfig, profile_name)


def save_active_pypi_env_value(
    key: str,
    value: str,
    *,
    home: str | Path | None = None,
) -> Path:
    """Save one active PyPI env value via ChatEnv's native store."""

    store = EnvStore(get_paths(home).envs_dir)
    values = store.load_active(PyPIConfig)
    values[key] = value
    return store.save_active(PyPIConfig, values)


def save_pypi_env_profile_value(
    profile_name: str,
    key: str,
    value: str,
    *,
    home: str | Path | None = None,
) -> Path:
    """Save one value to a named PyPI ChatEnv profile without activating it."""

    store = EnvStore(get_paths(home).envs_dir)
    values = store.load_profile(PyPIConfig, profile_name)
    values[key] = value
    return store.save_profile(PyPIConfig, profile_name, values)


setattr(
    PyPIConfig,
    "PYPI_USERNAME",
    EnvField("PYPI_USERNAME", desc="PyPI username"),
)
setattr(
    PyPIConfig,
    "PYPI_EMAIL",
    EnvField("PYPI_EMAIL", desc="PyPI account email"),
)
setattr(
    PyPIConfig,
    "PYPI_NAME",
    EnvField("PYPI_NAME", desc="PyPI account display/full name"),
)
setattr(
    PyPIConfig,
    "PYPI_PASSWORD",
    EnvField("PYPI_PASSWORD", desc="PyPI account password", is_sensitive=True),
)
setattr(
    PyPIConfig,
    "PYPI_API_TOKEN",
    EnvField("PYPI_API_TOKEN", desc="PyPI API token", is_sensitive=True),
)
setattr(
    PyPIConfig,
    "PYPI_TOTP_SECRET",
    EnvField("PYPI_TOTP_SECRET", desc="PyPI TOTP seed/secret", is_sensitive=True),
)
setattr(
    PyPIConfig,
    "PYPI_SESSION_TOKEN",
    EnvField(
        "PYPI_SESSION_TOKEN",
        desc="Serialized PyPI web session token captured by chatpypi auth login",
        is_sensitive=True,
    ),
)
__all__ = [
    "SESSION_TOKEN_ENV",
    "PyPIConfig",
    "load_active_pypi_env",
    "load_pypi_env_profile",
    "save_active_pypi_env_value",
    "save_pypi_env_profile_value",
]
