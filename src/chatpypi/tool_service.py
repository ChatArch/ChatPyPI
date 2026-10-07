"""One Click-derived tool catalog and in-process invocation adapter."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from threading import Lock
import tempfile
from typing import Any

import click
from click.testing import CliRunner


_LOCAL_GROUPS = {"mirror"}
_LOCAL_LEAVES = {"init", "build", "check"}
_SERVER_GROUPS = {"project", "publisher", "doctor", "docs"}
_SERVER_LEAVES = {"probe", "upload"}
_CAPTURE_LOCK = Lock()
MAX_ARTIFACT_SIZE = 10 * 1024 * 1024
MAX_UPLOAD_SIZE = 20 * 1024 * 1024


def _upload_schema() -> dict[str, Any]:
    artifact = {
        "type": "object",
        "additionalProperties": False,
        "required": ["filename", "content_base64", "size", "sha256"],
        "properties": {
            "filename": {"type": "string", "maxLength": 200},
            "content_base64": {"type": "string", "maxLength": 13_981_020},
            "size": {"type": "integer", "minimum": 1, "maximum": MAX_ARTIFACT_SIZE},
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["artifacts"],
        "properties": {
            "artifacts": {"type": "array", "minItems": 1, "maxItems": 4, "items": artifact},
            "repository": {"type": "string", "enum": ["testpypi", "pypi"], "default": "pypi"},
            "skip_existing": {"type": "boolean", "default": False},
        },
    }


@dataclass(frozen=True)
class ToolSpec:
    name: str
    path: tuple[str, ...]
    command: click.Command
    policy: str
    input_schema: dict[str, Any]
    description: str

    @property
    def route(self) -> str:
        return "/api/" + "/".join(self.path)

    @property
    def read_only(self) -> bool:
        return self.name not in {"pkg_upload", "publisher_add_github", "publisher_pending_add", "publisher_pending_remove"}


def _json_type(parameter: click.Parameter) -> dict[str, Any]:
    if isinstance(parameter.type, click.Choice):
        return {"type": "string", "enum": list(parameter.type.choices)}
    if isinstance(parameter.type, click.types.BoolParamType):
        return {"type": "boolean"}
    if isinstance(parameter.type, click.types.IntParamType):
        return {"type": "integer"}
    if isinstance(parameter.type, click.types.FloatParamType):
        return {"type": "number"}
    return {"type": "string"}


def _schema(command: click.Command, *, server: bool) -> dict[str, Any]:
    if server and command.callback and command.callback.__name__ == "upload":
        return _upload_schema()
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in command.params:
        if parameter.multiple or parameter.nargs != 1:
            raise ValueError(f"Unsupported Click parameter shape for tool schema: {parameter.name}")
        if server and (parameter.name == "env_profile" or parameter.name in {"repository_url", "project_dir"}):
            continue
        item = _json_type(parameter)
        if parameter.help if isinstance(parameter, click.Option) else None:
            item["description"] = parameter.help
        default = parameter.default
        if default is not None and default is not click.core.ParameterSource.DEFAULT:
            if not type(default).__name__.endswith("Sentinel") and isinstance(default, (str, int, float, bool)):
                item["default"] = default
        properties[parameter.name] = item
        if parameter.required or (server and parameter.name == "package_name"):
            required.append(parameter.name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _policy(path: tuple[str, ...]) -> str | None:
    if path[0] in _LOCAL_GROUPS or (path[0] == "pkg" and path[-1] in _LOCAL_LEAVES):
        return "local"
    if path[0] in _SERVER_GROUPS or (path[0] == "pkg" and path[-1] in _SERVER_LEAVES):
        return "server"
    return None


def _leaves(group: click.Group, path: tuple[str, ...] = ()):
    for name, command in group.commands.items():
        child_path = (*path, name)
        if isinstance(command, click.Group):
            yield from _leaves(command, child_path)
        else:
            yield child_path, command


def build_catalog(root: click.Group) -> dict[str, ToolSpec]:
    """Derive implemented tools from Click callbacks, with aliases deduplicated."""

    catalog: dict[str, ToolSpec] = {}
    callbacks: set[int] = set()
    leaves = sorted(_leaves(root), key=lambda item: (len(item[0]) == 1, item[0]))
    for path, command in leaves:
        policy = _policy(path)
        callback = command.callback
        if policy is None or callback is None or callback.__name__ == "_command":
            continue
        callback_id = id(callback)
        if callback_id in callbacks:
            continue
        callbacks.add(callback_id)
        name = "_".join(path).replace("-", "_")
        catalog[name] = ToolSpec(
            name=name,
            path=path,
            command=command,
            policy=policy,
            input_schema=_schema(command, server=policy == "server"),
            description=(command.help or "").strip(),
        )
    return catalog


def catalog_payload(root: click.Group, *, policy: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "command": " ".join(spec.path),
            "route": spec.route,
            "policy": spec.policy,
            "methods": ["GET", "POST"] if spec.read_only else ["POST"],
            "description": spec.description,
            "input_schema": spec.input_schema,
        }
        for spec in build_catalog(root).values()
        if policy is None or spec.policy == policy
    ]


def _argument_vector(spec: ToolSpec, arguments: dict[str, Any], bound_profile: str | None) -> list[str]:
    validate_tool_arguments(spec, arguments)
    allowed = set(spec.input_schema["properties"])
    unknown = set(arguments) - allowed
    if unknown:
        raise ValueError(f"Unknown tool argument(s): {', '.join(sorted(unknown))}")
    missing = set(spec.input_schema.get("required", ())) - set(arguments)
    if missing:
        raise ValueError(f"Missing tool argument(s): {', '.join(sorted(missing))}")

    argv: list[str] = []
    for parameter in spec.command.params:
        if parameter.name == "env_profile":
            if bound_profile:
                argv.extend(["--env-profile", bound_profile])
            continue
        if parameter.name not in arguments or arguments[parameter.name] is None:
            continue
        value = arguments[parameter.name]
        if isinstance(parameter, click.Argument):
            argv.append(str(value))
            continue
        if parameter.is_flag:
            if bool(value):
                argv.append(next((opt for opt in parameter.opts if opt.startswith("--")), parameter.opts[0]))
            elif parameter.secondary_opts:
                argv.append(next((opt for opt in parameter.secondary_opts if opt.startswith("--")), parameter.secondary_opts[0]))
            continue
        option = next((opt for opt in parameter.opts if opt.startswith("--")), parameter.opts[0])
        argv.extend([option, str(value)])
    return argv


def _valid_artifact_name(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 200
        and Path(value).name == value
        and not value.startswith(".")
        and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value))
        and value.endswith((".whl", ".tar.gz", ".zip"))
    )


def validate_tool_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise ValueError("Tool input must be an object.")
    schema = spec.input_schema
    properties = schema["properties"]
    unknown = set(arguments) - set(properties)
    missing = set(schema.get("required", ())) - set(arguments)
    if unknown:
        raise ValueError(f"Unknown tool argument(s): {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"Missing tool argument(s): {', '.join(sorted(missing))}")
    for name, value in arguments.items():
        expected = properties[name]
        kind = expected.get("type")
        valid = {
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "array": isinstance(value, list),
        }.get(kind, False)
        if not valid or ("enum" in expected and value not in expected["enum"]):
            raise ValueError(f"Invalid value for tool argument: {name}")
    if spec.name != "pkg_upload":
        return
    artifacts = arguments["artifacts"]
    if not 1 <= len(artifacts) <= 4:
        raise ValueError("Upload requires between one and four artifacts.")
    total = 0
    names: set[str] = set()
    keys = {"filename", "content_base64", "size", "sha256"}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != keys:
            raise ValueError("Each upload artifact must contain only filename, content_base64, size, and sha256.")
        filename, size = artifact["filename"], artifact["size"]
        if not isinstance(filename, str) or not _valid_artifact_name(filename) or filename in names:
            raise ValueError("Upload artifact filename is invalid or duplicated.")
        if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_ARTIFACT_SIZE:
            raise ValueError("Upload artifact size is invalid.")
        if not isinstance(artifact["content_base64"], str) or len(artifact["content_base64"]) > 13_981_020:
            raise ValueError("Upload artifact content is invalid.")
        if not isinstance(artifact["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
            raise ValueError("Upload artifact digest is invalid.")
        names.add(filename)
        total += size
    if total > MAX_UPLOAD_SIZE:
        raise ValueError("Upload artifact total exceeds the 20 MiB limit.")


def _invoke_upload(arguments: dict[str, Any], bound_profile: str | None) -> dict[str, Any]:
    from chatpypi.config import load_pypi_env_profile
    from chatpypi.main import PyPICommandError, upload_distributions

    if not bound_profile:
        return {"tool": "pkg_upload", "exit_code": 1, "stdout": "", "stderr": "Error: Upload profile binding is required.\n"}
    try:
        values = load_pypi_env_profile(bound_profile)
        secret = str(values.get("PYPI_API_TOKEN") or "")
    except (FileNotFoundError, ValueError):
        secret = ""
    if not secret:
        return {"tool": "pkg_upload", "exit_code": 1, "stdout": "", "stderr": "Error: Bound upload credential is unavailable.\n"}
    try:
        from chatenv import get_paths

        upload_root = get_paths().home_dir / "chatpypi" / "uploads"
        upload_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="chatpypi-upload-", dir=upload_root) as directory:
            project_dir = Path(directory)
            dist_dir = project_dir / "dist"
            dist_dir.mkdir(mode=0o700)
            for artifact in arguments["artifacts"]:
                try:
                    content = base64.b64decode(artifact["content_base64"], validate=True)
                except (binascii.Error, ValueError):
                    raise ValueError("Upload artifact encoding is invalid.") from None
                if len(content) != artifact["size"] or hashlib.sha256(content).hexdigest() != artifact["sha256"]:
                    raise ValueError("Upload artifact size or digest does not match.")
                (dist_dir / artifact["filename"]).write_bytes(content)
            result, files = upload_distributions(
                project_dir,
                dist_dir,
                skip_existing=arguments.get("skip_existing", False),
                repository=arguments.get("repository", "pypi"),
                repository_url=None,
                username="__token__",
                env={"TWINE_PASSWORD": secret, "TWINE_NON_INTERACTIVE": "1"},
            )
            stdout = result.stdout.replace(secret, "[REDACTED]").replace(str(project_dir), "[TEMP]").strip()
            stderr = result.stderr.replace(secret, "[REDACTED]").replace(str(project_dir), "[TEMP]").strip()
            lines = ["Uploading managed distributions with `twine upload`..."]
            if stdout:
                lines.append(stdout)
            lines.extend(["Uploaded distributions:", *(f"- {path.name}" for path in files)])
            return {"tool": "pkg_upload", "exit_code": 0, "stdout": "\n".join(lines) + "\n", "stderr": (stderr + "\n") if stderr else ""}
    except ValueError:
        return {"tool": "pkg_upload", "exit_code": 2, "stdout": "", "stderr": "Error: Upload artifact validation failed.\n"}
    except (PyPICommandError, OSError):
        return {"tool": "pkg_upload", "exit_code": 1, "stdout": "", "stderr": "Error: Upload failed.\n"}


def invoke_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    bound_profile: str | None = None,
) -> dict[str, Any]:
    """Invoke an existing Click capability without a subprocess or shell."""

    from chatpypi.cli import cli

    catalog = build_catalog(cli)
    try:
        spec = catalog[name]
    except KeyError as exc:
        raise ValueError(f"Unknown ChatPyPI tool: {name}") from exc
    supplied = arguments or {}
    validate_tool_arguments(spec, supplied)
    if name == "pkg_upload":
        return _invoke_upload(supplied, bound_profile)
    argv = ["--mode", "local", *spec.path, *_argument_vector(spec, supplied, bound_profile)]
    with _CAPTURE_LOCK:
        result = CliRunner().invoke(cli, argv, catch_exceptions=True)
    payload = {
        "tool": name,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.exception and not isinstance(result.exception, SystemExit):
        payload["error"] = type(result.exception).__name__
    return payload


def parse_remote_invocation(root: click.Group, args: list[str]) -> tuple[ToolSpec | None, dict[str, Any]]:
    """Parse one Click leaf while retaining only caller-supplied parameter values."""

    catalog = build_catalog(root)
    by_path = {spec.path: spec for spec in catalog.values()}
    by_callback = {id(spec.command.callback): spec for spec in catalog.values()}
    path: list[str] = []
    command: click.Command = root
    remaining = list(args)
    parent: click.Context | None = None
    while isinstance(command, click.Group) and remaining:
        name = remaining.pop(0)
        child = command.commands.get(name)
        if child is None:
            return None, {}
        path.append(name)
        command = child
    spec = by_path.get(tuple(path)) or by_callback.get(id(command.callback))
    if spec is None:
        return None, {}
    ctx = command.make_context(" ".join(path), remaining, parent=parent)
    explicit = {
        parameter.name: ctx.params[parameter.name]
        for parameter in command.params
        if parameter.name in ctx.params
        and parameter.name != "env_profile"
        and ctx.get_parameter_source(parameter.name) != click.core.ParameterSource.DEFAULT
    }
    return spec, explicit


__all__ = ["ToolSpec", "build_catalog", "catalog_payload", "invoke_tool", "parse_remote_invocation", "validate_tool_arguments"]
