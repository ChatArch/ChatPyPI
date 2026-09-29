"""Safe current-user uv and pip download-index configuration."""

from __future__ import annotations

from configparser import ConfigParser, Error as ConfigParserError
from dataclasses import dataclass
import os
from pathlib import Path
from io import StringIO
import stat
import sys
import tempfile
from typing import Mapping

import tomlkit
from tomlkit.exceptions import TOMLKitError


DEFAULT_URL = "https://pypi.org/simple"
TSINGHUA_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
PRESET_URLS = {"default": DEFAULT_URL, "tsinghua": TSINGHUA_URL}

UV_OVERRIDE_KEYS = (
    "UV_DEFAULT_INDEX",
    "UV_INDEX_URL",
    "UV_CONFIG_FILE",
    "UV_INDEX",
    "UV_EXTRA_INDEX_URL",
)
PIP_OVERRIDE_KEYS = (
    "PIP_INDEX_URL",
    "PIP_CONFIG_FILE",
    "PIP_EXTRA_INDEX_URL",
)


class MirrorConfigError(RuntimeError):
    """Raised when user mirror configuration cannot be handled safely."""


@dataclass(frozen=True)
class UserConfigPaths:
    uv: Path
    pip: Path
    pip_legacy: Path


def resolve_user_config_paths(
    *,
    home: Path | str | None = None,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> UserConfigPaths:
    """Resolve the native current-user config paths used by uv and pip."""

    environment = os.environ if env is None else env
    platform_name = sys.platform if platform is None else platform
    home_path = Path(home).expanduser() if home is not None else Path.home()

    if platform_name.startswith("win"):
        appdata = Path(environment.get("APPDATA") or home_path / "AppData/Roaming")
        return UserConfigPaths(
            uv=appdata / "uv/uv.toml",
            pip=appdata / "pip/pip.ini",
            pip_legacy=home_path / "pip/pip.ini",
        )

    xdg_config = Path(environment.get("XDG_CONFIG_HOME") or home_path / ".config")
    uv_path = xdg_config / "uv/uv.toml"
    legacy = home_path / ".pip/pip.conf"
    if platform_name == "darwin":
        xdg_data_value = environment.get("XDG_DATA_HOME")
        if xdg_data_value and (Path(xdg_data_value) / "pip").is_dir():
            pip_path = Path(xdg_data_value) / "pip/pip.conf"
        elif not xdg_data_value and (
            home_path / "Library/Application Support/pip"
        ).is_dir():
            pip_path = home_path / "Library/Application Support/pip/pip.conf"
        else:
            pip_path = home_path / ".config/pip/pip.conf"
    else:
        pip_path = xdg_config / "pip/pip.conf"
    return UserConfigPaths(uv=uv_path, pip=pip_path, pip_legacy=legacy)


def _paths(
    *,
    uv_path: Path | str | None,
    pip_path: Path | str | None,
    pip_legacy_path: Path | str | None,
    home: Path | str | None,
    platform: str | None,
    env: Mapping[str, str] | None,
) -> UserConfigPaths:
    resolved = resolve_user_config_paths(home=home, platform=platform, env=env)
    return UserConfigPaths(
        uv=Path(uv_path) if uv_path is not None else resolved.uv,
        pip=Path(pip_path) if pip_path is not None else resolved.pip,
        pip_legacy=(
            Path(pip_legacy_path)
            if pip_legacy_path is not None
            else resolved.pip_legacy
        ),
    )


def _selected_tools(tool: str) -> tuple[str, ...]:
    if tool == "all":
        return ("uv", "pip")
    if tool in {"uv", "pip"}:
        return (tool,)
    raise MirrorConfigError("Tool must be one of: uv, pip, all.")


def _read_file(path: Path, label: str) -> bytes | None:
    failed = False
    try:
        content = path.read_bytes() if path.exists() else None
    except OSError:
        failed, content = True, None
    if failed:
        raise MirrorConfigError(f"Unable to read {label} user configuration.")
    return content


def _decode(content: bytes | None, label: str) -> str:
    if content is None:
        return ""
    failed = False
    try:
        result = content.decode("utf-8")
    except UnicodeDecodeError:
        failed, result = True, ""
    if failed:
        raise MirrorConfigError(f"Unable to parse {label} user configuration.")
    return result


def _parse_uv(content: bytes | None):
    text = _decode(content, "uv")
    failed = False
    try:
        document = tomlkit.parse(text)
    except (TOMLKitError, ValueError, TypeError):
        failed, document = True, None
    if failed:
        raise MirrorConfigError("Unable to parse uv user configuration.")
    return document


def _parse_pip(content: bytes | None):
    text = _decode(content, "pip")
    parser = ConfigParser(interpolation=None, strict=True)
    failed = False
    try:
        parser.read_string(text)
    except (ConfigParserError, ValueError):
        failed = True
    if failed:
        raise MirrorConfigError("Unable to parse pip user configuration.")
    return parser


def _normalized_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().rstrip("/")


def _preset_for_url(value: object) -> str:
    normalized = _normalized_url(value)
    if normalized == DEFAULT_URL.rstrip("/"):
        return "default"
    if normalized == TSINGHUA_URL.rstrip("/"):
        return "tsinghua"
    return "custom" if normalized else "unset"


def _public_url(value: object) -> str | None:
    preset = _preset_for_url(value)
    if preset == "default":
        return DEFAULT_URL
    if preset == "tsinghua":
        return TSINGHUA_URL
    if preset == "custom":
        return "REDACTED"
    return None


def _uv_default_value(document) -> tuple[object, str]:
    indexes = document.get("index")
    defaults = []
    if isinstance(indexes, list):
        defaults = [item for item in indexes if isinstance(item, dict) and item.get("default") is True]
    if len(defaults) > 1:
        return None, "ambiguous-user"
    if defaults:
        return defaults[0].get("url"), "user"
    for key in ("default-index", "index-url"):
        if key in document:
            return document.get(key), "legacy-user"
    pip_table = document.get("pip")
    if isinstance(pip_table, dict) and "index-url" in pip_table:
        return pip_table.get("index-url"), "legacy-user-pip"
    return None, "user"


def _uv_summary(path: Path, content: bytes | None) -> dict[str, object]:
    document = _parse_uv(content)
    value, source = _uv_default_value(document)
    preset = _preset_for_url(value)
    return {
        "path": str(path),
        "scope": "user",
        "source": source,
        "preset": "custom" if source == "ambiguous-user" else preset,
        "url": "REDACTED" if source == "ambiguous-user" else _public_url(value),
    }


def _pip_value(parser: ConfigParser) -> object:
    if not parser.has_section("global"):
        return None
    value = None
    for key, candidate in parser.items("global"):
        if key.lower().replace("_", "-") == "index-url":
            value = candidate
    return value


def _pip_summary(
    path: Path,
    content: bytes | None,
    legacy_path: Path,
    legacy_content: bytes | None,
) -> dict[str, object]:
    parser = _parse_pip(content)
    legacy_parser = _parse_pip(legacy_content)
    value = _pip_value(parser)
    source = "user"
    if value is None:
        value = _pip_value(legacy_parser)
        if value is not None:
            source = "legacy-user"
    return {
        "path": str(path),
        "legacy_path": str(legacy_path),
        "scope": "user",
        "source": source,
        "preset": _preset_for_url(value),
        "url": _public_url(value),
    }


def _override_keys(tool: str, env: Mapping[str, str]) -> list[str]:
    selected = _selected_tools(tool)
    candidates: list[str] = []
    if "uv" in selected:
        candidates.extend(UV_OVERRIDE_KEYS)
    if "pip" in selected:
        candidates.extend(PIP_OVERRIDE_KEYS)
    return [key for key in candidates if key in env]


def _base_result(tool: str, env: Mapping[str, str]) -> dict[str, object]:
    keys = _override_keys(tool, env)
    warnings = []
    if keys:
        warnings.append(
            "Environment overrides detected: "
            + ", ".join(keys)
            + ". Values are hidden; user configuration may not be effective."
        )
    return {"scope": "user", "override_keys": keys, "warnings": warnings}


def show_mirrors(
    *,
    tool: str = "all",
    uv_path: Path | str | None = None,
    pip_path: Path | str | None = None,
    pip_legacy_path: Path | str | None = None,
    home: Path | str | None = None,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Inspect native current-user mirror settings without exposing custom URLs."""

    environment = os.environ if env is None else env
    paths = _paths(
        uv_path=uv_path,
        pip_path=pip_path,
        pip_legacy_path=pip_legacy_path,
        home=home,
        platform=platform,
        env=environment,
    )
    selected = _selected_tools(tool)
    tools: dict[str, object] = {}
    if "uv" in selected:
        tools["uv"] = _uv_summary(paths.uv, _read_file(paths.uv, "uv"))
    if "pip" in selected:
        pip_content = _read_file(paths.pip, "pip")
        legacy_content = (
            pip_content
            if paths.pip_legacy == paths.pip
            else _read_file(paths.pip_legacy, "pip legacy")
        )
        tools["pip"] = _pip_summary(
            paths.pip, pip_content, paths.pip_legacy, legacy_content
        )
    result = _base_result(tool, environment)
    result["tools"] = tools
    return result


def _prepare_uv(content: bytes | None, url: str) -> bytes:
    document = _parse_uv(content)
    indexes = document.get("index")
    if indexes is not None and not isinstance(indexes, list):
        raise MirrorConfigError("Unable to safely update ambiguous uv index configuration.")

    defaults = [] if indexes is None else [
        item for item in indexes if isinstance(item, dict) and item.get("default") is True
    ]
    if len(defaults) > 1:
        raise MirrorConfigError("Unable to safely update ambiguous uv default indexes.")
    if defaults and _preset_for_url(defaults[0].get("url")) == "custom":
        raise MirrorConfigError("Refusing to replace a custom uv default index.")
    if defaults and defaults[0].get("name") and _normalized_url(defaults[0].get("url")) != url:
        raise MirrorConfigError("Refusing to retarget a named uv default index or its auth binding.")

    legacy_locations: list[tuple[object, str]] = []
    for key in ("default-index", "index-url"):
        if key in document:
            legacy_locations.append((document, key))
    pip_table = document.get("pip")
    if isinstance(pip_table, dict) and "index-url" in pip_table:
        legacy_locations.append((pip_table, "index-url"))
    for table, key in legacy_locations:
        if _preset_for_url(table.get(key)) not in {"default", "tsinghua"}:
            raise MirrorConfigError("Refusing to replace a custom uv legacy index setting.")

    for table, key in legacy_locations:
        del table[key]

    if defaults:
        defaults[0]["url"] = url
    else:
        if indexes is None:
            indexes = tomlkit.aot()
            document["index"] = indexes
        entry = tomlkit.table()
        entry.add("url", url)
        entry.add("default", True)
        indexes.append(entry)
    return tomlkit.dumps(document).encode("utf-8")


def _prepare_pip(content: bytes | None, url: str) -> bytes:
    parser = _parse_pip(content)
    if not parser.has_section("global"):
        parser.add_section("global")
    for key in list(parser.options("global")):
        if key.lower().replace("_", "-") == "index-url":
            parser.remove_option("global", key)
    parser.set("global", "index-url", url)
    output = StringIO()
    parser.write(output)
    result = output.getvalue()
    if content and b"\r\n" in content:
        result = result.replace("\n", "\r\n")
    return result.encode("utf-8")


def _refuse_symlink(path: Path, label: str) -> None:
    try:
        if path.is_symlink():
            raise MirrorConfigError(
                f"Refusing to replace a symbolic link at the {label} user config path."
            )
    except OSError:
        raise MirrorConfigError(f"Unable to inspect {label} user configuration.") from None


def _stage(path: Path, content: bytes) -> Path:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        stage = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            stage.unlink(missing_ok=True)
            raise
        return stage
    except OSError:
        raise MirrorConfigError("Unable to stage user mirror configuration safely.") from None


def _restore(path: Path, content: bytes | None, mode: int) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    stage = _stage(path, content)
    try:
        os.chmod(stage, mode)
        os.replace(stage, path)
    finally:
        stage.unlink(missing_ok=True)


def _write_transaction(changes: list[tuple[Path, bytes, bytes | None]]) -> None:
    staged: list[tuple[Path, Path, bytes | None, int]] = []
    stage_failed = False
    try:
        for path, content, original in changes:
            mode = stat.S_IMODE(path.stat().st_mode) if original is not None else 0o600
            staged.append((path, _stage(path, content), original, mode))
    except (OSError, MirrorConfigError):
        stage_failed = True
    if stage_failed:
        for _, stage, _, _ in staged:
            stage.unlink(missing_ok=True)
        raise MirrorConfigError("Unable to stage user mirror configuration safely.")

    replaced: list[tuple[Path, bytes | None, int]] = []
    write_failed = False
    try:
        for path, stage, original, mode in staged:
            os.chmod(stage, mode)
            os.replace(stage, path)
            replaced.append((path, original, mode))
    except OSError:
        write_failed = True
    rollback_failed = False
    if write_failed:
        for path, original, mode in reversed(replaced):
            try:
                _restore(path, original, mode)
            except (OSError, MirrorConfigError):
                rollback_failed = True
    for _, stage, _, _ in staged:
        stage.unlink(missing_ok=True)
    if write_failed:
        message = (
            "User mirror configuration transaction failed and rollback could not be completed safely."
            if rollback_failed
            else "User mirror configuration transaction failed; completed changes were rolled back."
        )
        raise MirrorConfigError(message)


def set_mirrors(
    preset: str,
    *,
    tool: str = "all",
    dry_run: bool = False,
    uv_path: Path | str | None = None,
    pip_path: Path | str | None = None,
    pip_legacy_path: Path | str | None = None,
    home: Path | str | None = None,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Persist a public preset in native current-user uv and/or pip config."""

    if preset not in PRESET_URLS:
        raise MirrorConfigError("Preset must be one of: default, tsinghua.")
    environment = os.environ if env is None else env
    paths = _paths(
        uv_path=uv_path,
        pip_path=pip_path,
        pip_legacy_path=pip_legacy_path,
        home=home,
        platform=platform,
        env=environment,
    )
    selected = _selected_tools(tool)
    if len(selected) > 1 and paths.uv.resolve() == paths.pip.resolve():
        raise MirrorConfigError("uv and pip require distinct user configuration paths.")
    url = PRESET_URLS[preset]
    originals: dict[str, bytes | None] = {}
    prepared: dict[str, bytes] = {}

    if "uv" in selected:
        _refuse_symlink(paths.uv, "uv")
        originals["uv"] = _read_file(paths.uv, "uv")
        prepared["uv"] = _prepare_uv(originals["uv"], url)
    if "pip" in selected:
        _refuse_symlink(paths.pip, "pip")
        originals["pip"] = _read_file(paths.pip, "pip")
        # Validate legacy user config too because pip loads it before the current file.
        if paths.pip_legacy != paths.pip:
            _parse_pip(_read_file(paths.pip_legacy, "pip legacy"))
        prepared["pip"] = _prepare_pip(originals["pip"], url)

    path_by_tool = {"uv": paths.uv, "pip": paths.pip}
    changes = [
        (path_by_tool[name], prepared[name], originals[name])
        for name in selected
        if prepared[name] != originals[name]
    ]
    if changes and not dry_run:
        _write_transaction(changes)

    tools: dict[str, object] = {}
    for name in selected:
        changed = prepared[name] != originals[name]
        tools[name] = {
            "path": str(path_by_tool[name]),
            "scope": "user",
            "preset": preset,
            "url": url,
            "status": "would-change" if dry_run and changed else "changed" if changed else "unchanged",
        }
    result = _base_result(tool, environment)
    result.update(
        {"action": "set", "preset": preset, "dry_run": dry_run, "tools": tools}
    )
    return result
