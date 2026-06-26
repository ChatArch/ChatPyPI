"""ChatPyPI provider configuration helpers."""

from __future__ import annotations

from typing import Any

from chatenv.fields import BaseEnvConfig as _BaseEnvConfig, EnvField as _EnvField

BaseEnvConfig: Any = _BaseEnvConfig
EnvField: Any = _EnvField


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
    "PYPI_SESSION_FILE",
    EnvField("PYPI_SESSION_FILE", desc="Path to local PyPI session JSON file"),
)


__all__ = ["PyPIConfig"]
