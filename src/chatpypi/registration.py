"""Registration-only workflow and durable service state.

This module deliberately has no FastAPI or uvicorn import.  The HTTP surface is
an optional adapter over :class:`RegistrationManager`, and provider mutation
methods are narrow enough to replace with explicit fakes in tests.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import json
import keyword
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import tempfile
from typing import Any, Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from uuid import UUID, uuid4

from chatenv.paths import get_paths
from chatenv.store import EnvStore

from chatpypi.config import RegistrationAPIConfig, load_active_pypi_env
from chatpypi.registration_errors import ERROR_STATUS_CODES, SAFE_ERROR_MESSAGES
from chatpypi.main import (
    CommandResult,
    PyPICommandError,
    build_package,
    check_distributions,
    check_repository_conflicts,
    normalize_module_name,
    scaffold_package,
    upload_distributions,
)
from chatpypi.session_ops import (
    PyPISessionError,
    add_github_publisher_to_project_from_payload,
    list_projects_from_payload,
    load_session_payload_from_env,
    validate_session_payload,
)


INITIAL_VERSION = "0.0.1"
DEFAULT_BRANCH = "main"
PUBLISH_WORKFLOW = "publish.yml"
REGISTRATION_STAGES = (
    "credentials",
    "preflight",
    "scaffold",
    "tests",
    "build_check",
    "pypi_upload",
    "pypi_readback",
    "public_install",
    "github_repository",
    "source_push",
    "public_protection",
    "trusted_publisher",
    "github_readback",
)
MAX_PREFLIGHT_NAMES = 20
MAX_DESCRIPTION_LENGTH = 240
MAX_COMMAND_OUTPUT = 16 * 1024

_DIST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")

class RegistrationError(RuntimeError):
    """A safe, categorized error suitable for durable/public state."""

    def __init__(self, category: str):
        if category not in SAFE_ERROR_MESSAGES:
            category = "local_execution"
        self.category = category
        self.safe_message = SAFE_ERROR_MESSAGES[category]
        self.status_code = ERROR_STATUS_CODES[category]
        super().__init__(self.safe_message)


class _ReconciliationRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceConfig:
    """Validated service configuration loaded from the ChatEnv schema."""

    api_token: str
    host: str
    port: int
    allowed_hosts: tuple[str, ...]
    allowed_owners: tuple[str, ...]
    registration_enabled: bool
    chatarch_home: Path
    state_dir: Path
    max_body_bytes: int = 64 * 1024
    max_queue: int = 32
    max_requests_per_minute: int = 120
    command_timeout: float = 300.0
    provider_timeout: float = 20.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_bool(value: object, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RegistrationError("invalid_request")


def _parse_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = default if value in {None, ""} else int(str(value))
    except (TypeError, ValueError):
        raise RegistrationError("invalid_request") from None
    if parsed < minimum or parsed > maximum:
        raise RegistrationError("invalid_request")
    return parsed


def _csv_values(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None or not str(value).strip():
        return default
    items = tuple(item.strip() for item in str(value).split(",") if item.strip())
    if not items:
        raise RegistrationError("invalid_request")
    return items


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def validate_service_config(config: ServiceConfig) -> ServiceConfig:
    if (
        not config.api_token
        or not 16 <= len(config.api_token) <= 512
        or any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in config.api_token)
    ):
        raise RegistrationError("service_auth_missing")
    if not config.allowed_hosts or any(
        not host
        or "*" in host
        or any(char.isspace() or ord(char) < 32 for char in host)
        for host in config.allowed_hosts
    ):
        raise RegistrationError("invalid_request")
    if not config.allowed_owners or any(
        not _OWNER_RE.fullmatch(owner) for owner in config.allowed_owners
    ):
        raise RegistrationError("invalid_request")
    if not (1 <= config.port <= 65535):
        raise RegistrationError("invalid_request")
    if config.max_body_bytes < 128 or config.max_body_bytes > 1024 * 1024:
        raise RegistrationError("invalid_request")
    if config.max_queue < 1 or config.max_queue > 1000:
        raise RegistrationError("invalid_request")
    if not 1 <= config.max_requests_per_minute <= 10000:
        raise RegistrationError("invalid_request")
    if not _is_loopback_host(config.host):
        lowered = {item.lower() for item in config.allowed_hosts}
        if lowered <= {"localhost", "127.0.0.1", "[::1]", "::1", "testserver"}:
            raise RegistrationError("invalid_request")
    return config


def load_service_config(home: str | Path | None = None) -> ServiceConfig:
    """Load active API config without changing any active ChatEnv profile."""

    paths = get_paths(home)
    stored = EnvStore(paths.envs_dir).load_active(RegistrationAPIConfig)

    def value(key: str, default: object = None) -> object:
        return os.getenv(key, stored.get(key, default))

    host = str(value("CHATPYPI_API_HOST", "127.0.0.1")).strip()
    default_hosts = ("127.0.0.1", "localhost", "[::1]")
    config = ServiceConfig(
        api_token=str(value("CHATPYPI_API_TOKEN", "") or ""),
        host=host,
        port=_parse_int(value("CHATPYPI_API_PORT"), default=8765, minimum=1, maximum=65535),
        allowed_hosts=_csv_values(value("CHATPYPI_API_ALLOWED_HOSTS"), default_hosts),
        allowed_owners=_csv_values(value("CHATPYPI_API_ALLOWED_OWNERS"), ("ChatArch",)),
        registration_enabled=_parse_bool(
            value("CHATPYPI_REGISTRATION_ENABLED"), default=False
        ),
        chatarch_home=paths.home_dir,
        state_dir=paths.home_dir / "runtime" / "chatpypi" / "registration-api",
        max_body_bytes=_parse_int(
            value("CHATPYPI_API_MAX_BODY_BYTES"),
            default=64 * 1024,
            minimum=128,
            maximum=1024 * 1024,
        ),
        max_queue=_parse_int(
            value("CHATPYPI_API_MAX_QUEUE"), default=32, minimum=1, maximum=1000
        ),
        max_requests_per_minute=_parse_int(
            value("CHATPYPI_API_RATE_LIMIT_PER_MINUTE"),
            default=120,
            minimum=1,
            maximum=10000,
        ),
    )
    return validate_service_config(config)


def registration_paths(home: str | Path | None = None) -> dict[str, str]:
    paths = get_paths(home)
    return {
        "chatarch_home": str(paths.home_dir),
        "registration_state": str(
            paths.home_dir / "runtime" / "chatpypi" / "registration-api"
        ),
    }


def normalize_distribution_name(value: str) -> str:
    if not isinstance(value, str):
        raise RegistrationError("invalid_request")
    stripped = value.strip()
    if not _DIST_RE.fullmatch(stripped):
        raise RegistrationError("invalid_request")
    return re.sub(r"[-_.]+", "-", stripped).lower()


def _validated_module_name(distribution: str) -> str:
    try:
        module = normalize_module_name(distribution)
    except PyPICommandError:
        raise RegistrationError("invalid_request") from None
    if not module.isidentifier() or keyword.iskeyword(module):
        raise RegistrationError("invalid_request")
    return module


def _validate_distribution(value: object) -> tuple[str, str, str]:
    if not isinstance(value, str):
        raise RegistrationError("invalid_request")
    distribution = value.strip()
    normalized = normalize_distribution_name(distribution)
    module = _validated_module_name(distribution)
    return distribution, normalized, module


def _validate_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise RegistrationError("invalid_request")
    try:
        parsed = UUID(value)
    except ValueError:
        raise RegistrationError("invalid_request") from None
    if str(parsed) != value:
        raise RegistrationError("invalid_request")
    return value


def _validated_owner(value: object, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or not _OWNER_RE.fullmatch(value.strip()):
        raise RegistrationError("invalid_request")
    matches = [owner for owner in allowed if owner.lower() == value.strip().lower()]
    if len(matches) != 1:
        raise RegistrationError("invalid_request")
    return matches[0]


def _validate_plan_request(payload: dict[str, Any], config: ServiceConfig) -> dict[str, str]:
    allowed_keys = {"distribution", "description", "owner", "visibility"}
    if not isinstance(payload, dict) or set(payload) - allowed_keys:
        raise RegistrationError("invalid_request")
    distribution, normalized, module = _validate_distribution(payload.get("distribution"))
    owner = _validated_owner(payload.get("owner"), config.allowed_owners)
    visibility = payload.get("visibility", "private")
    if visibility not in {"private", "public"}:
        raise RegistrationError("invalid_request")
    description_value = payload.get("description")
    description = (
        f"{distribution} package"
        if description_value is None
        else str(description_value).strip()
    )
    if not description or len(description) > MAX_DESCRIPTION_LENGTH:
        raise RegistrationError("invalid_request")
    if any(ord(char) < 32 or ord(char) == 127 for char in description):
        raise RegistrationError("invalid_request")
    return {
        "distribution": distribution,
        "normalized_name": normalized,
        "module_name": module,
        "description": description,
        "owner": owner,
        "visibility": visibility,
    }


def _assert_private_state_path(home: Path, state_dir: Path) -> tuple[Path, Path]:
    home_abs = home.expanduser().absolute()
    state_abs = state_dir.expanduser().absolute()
    try:
        relative = state_abs.relative_to(home_abs)
    except ValueError:
        raise RegistrationError("unsafe_state") from None
    current = home_abs
    if current.is_symlink():
        raise RegistrationError("unsafe_state")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RegistrationError("unsafe_state")
    resolved_home = home_abs.resolve(strict=False)
    resolved_state = state_abs.resolve(strict=False)
    try:
        resolved_state.relative_to(resolved_home)
    except ValueError:
        raise RegistrationError("unsafe_state") from None
    return resolved_home, resolved_state


def _private_subdirectory(parent: Path, name: str) -> Path:
    parent_resolved = parent.resolve(strict=True)
    directory = parent_resolved / name
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise RegistrationError("unsafe_state")
    directory.mkdir(mode=0o700, exist_ok=True)
    resolved = directory.resolve(strict=True)
    try:
        resolved.relative_to(parent_resolved)
    except ValueError:
        raise RegistrationError("unsafe_state") from None
    resolved.chmod(0o700)
    return resolved


class RegistrationStore:
    def __init__(self, config: ServiceConfig):
        self.home, self.root = _assert_private_state_path(
            config.chatarch_home, config.state_dir
        )
        self._lock = threading.RLock()
        self._ensure_directory(self.home)
        runtime = self.home / "runtime"
        self._ensure_directory(runtime)
        self._ensure_directory(runtime / "chatpypi")
        self._ensure_directory(self.root)
        self.workspaces = self.root / "workspaces"
        self._ensure_directory(self.workspaces)
        self.db_path = self.root / "registration.sqlite3"
        self._ensure_database_file()
        self._lock_fd = self._acquire_executor_lock()
        try:
            self._initialize_schema()
        except Exception:
            self.close()
            raise

    def _acquire_executor_lock(self) -> int:
        try:
            import fcntl
        except ImportError:
            raise RegistrationError("unsafe_state") from None
        lock_path = self.root / "executor.lock"
        if lock_path.is_symlink() or (
            lock_path.exists() and not lock_path.is_file()
        ):
            raise RegistrationError("unsafe_state")
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            raise RegistrationError("executor_locked") from None
        return descriptor

    def close(self) -> None:
        descriptor = getattr(self, "_lock_fd", None)
        if descriptor is None:
            return
        self._lock_fd = None
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise RegistrationError("unsafe_state")
        path.mkdir(parents=False, exist_ok=True, mode=0o700)
        path.chmod(0o700)

    def _ensure_database_file(self) -> None:
        if self.db_path.is_symlink():
            raise RegistrationError("unsafe_state")
        if self.db_path.exists():
            if not self.db_path.is_file():
                raise RegistrationError("unsafe_state")
        else:
            descriptor = os.open(
                self.db_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.close(descriptor)
        self.db_path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    normalized_name TEXT NOT NULL,
                    body_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL REFERENCES plans(id),
                    normalized_name TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    submission_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    receipts_json TEXT NOT NULL,
                    error_category TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_name_status_idx
                    ON jobs(normalized_name, status);
                CREATE INDEX IF NOT EXISTS jobs_created_idx
                    ON jobs(created_at DESC);
                """
            )
        self.db_path.chmod(0o600)

    def recover_interrupted(self) -> None:
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'reconciliation_required',
                    error_category = 'interrupted',
                    error_message = ?,
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (SAFE_ERROR_MESSAGES["interrupted"], now),
            )

    def save_plan(self, plan: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO plans(id, normalized_name, body_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    plan["id"],
                    plan["normalized_name"],
                    _canonical_json(plan),
                    plan["created_at"],
                ),
            )

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT body_json FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            raise RegistrationError("plan_not_found")
        try:
            plan = json.loads(row["body_json"])
        except (TypeError, json.JSONDecodeError):
            raise RegistrationError("unsafe_state") from None
        if not isinstance(plan, dict) or not isinstance(plan.get("digest"), str):
            raise RegistrationError("unsafe_state")
        unsigned = dict(plan)
        stored_digest = unsigned.pop("digest")
        actual_digest = hashlib.sha256(
            _canonical_json(unsigned).encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(stored_digest, actual_digest):
            raise RegistrationError("unsafe_state")
        return plan

    def create_job(
        self,
        *,
        plan: dict[str, Any],
        confirmation: str,
        idempotency_key: str,
        max_queue: int,
    ) -> tuple[dict[str, Any], bool]:
        submission_hash = hashlib.sha256(
            _canonical_json(
                {"plan_id": plan["id"], "confirmation": confirmation}
            ).encode("utf-8")
        ).hexdigest()
        now = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["plan_id"] == plan["id"]
                    and existing["submission_hash"] == submission_hash
                ):
                    return self._job_from_row(existing), True
                raise RegistrationError("idempotency_conflict")

            active_count = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()[0]
            if active_count >= max_queue:
                raise RegistrationError("queue_full")
            busy = connection.execute(
                """
                SELECT id FROM jobs
                WHERE normalized_name = ?
                  AND status IN ('queued', 'running', 'reconciliation_required')
                LIMIT 1
                """,
                (plan["normalized_name"],),
            ).fetchone()
            if busy is not None:
                raise RegistrationError("target_busy")

            job_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO jobs(
                    id, plan_id, normalized_name, idempotency_key,
                    submission_hash, status, stage, receipts_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', 'queued', '[]', ?, ?)
                """,
                (
                    job_id,
                    plan["id"],
                    plan["normalized_name"],
                    idempotency_key,
                    submission_hash,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        assert row is not None
        return self._job_from_row(row), False

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> dict[str, Any]:
        try:
            receipts = json.loads(row["receipts_json"])
        except (TypeError, json.JSONDecodeError):
            raise RegistrationError("unsafe_state") from None
        if not isinstance(receipts, list):
            raise RegistrationError("unsafe_state")
        status = str(row["status"])
        stage = str(row["stage"])
        if status not in {
            "queued",
            "running",
            "blocked",
            "failed",
            "reconciliation_required",
            "registered",
        } or stage not in {"queued", "registered", *REGISTRATION_STAGES}:
            raise RegistrationError("unsafe_state")
        job = {
            "id": row["id"],
            "plan_id": row["plan_id"],
            "normalized_name": row["normalized_name"],
            "status": status,
            "stage": stage,
            "receipts": receipts,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if row["error_category"]:
            category = str(row["error_category"])
            if category not in SAFE_ERROR_MESSAGES:
                raise RegistrationError("unsafe_state")
            job["error"] = {
                "category": category,
                "message": SAFE_ERROR_MESSAGES[category],
            }
        else:
            job["error"] = None
        return job

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise RegistrationError("job_not_found")
        return self._job_from_row(row)

    def list_jobs(self, *, limit: int, offset: int) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        return {
            "items": [self._job_from_row(row) for row in rows],
            "count": len(rows),
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def set_running(self, job_id: str, stage: str) -> None:
        self._update(job_id, status="running", stage=stage, error=None)

    def set_stage(self, job_id: str, stage: str) -> None:
        self._update(job_id, status="running", stage=stage, error=None)

    def append_receipt(self, job_id: str, stage: str, data: dict[str, Any]) -> None:
        receipt = {"stage": stage, "status": "completed", "at": _utc_now()}
        receipt.update(data)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT receipts_json FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise RegistrationError("job_not_found")
            receipts = json.loads(row["receipts_json"])
            receipts.append(receipt)
            connection.execute(
                "UPDATE jobs SET receipts_json = ?, updated_at = ? WHERE id = ?",
                (_canonical_json(receipts), _utc_now(), job_id),
            )

    def set_terminal(self, job_id: str, status: str, category: str | None = None) -> None:
        error = None
        if category is not None:
            error = (category, SAFE_ERROR_MESSAGES[category])
        stage = "registered" if status == "registered" else self.get_job(job_id)["stage"]
        self._update(job_id, status=status, stage=stage, error=error)

    def _update(
        self,
        job_id: str,
        *,
        status: str,
        stage: str,
        error: tuple[str, str] | None,
    ) -> None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, stage = ?, error_category = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    stage,
                    error[0] if error else None,
                    error[1] if error else None,
                    _utc_now(),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RegistrationError("job_not_found")

    def workspace_for(self, job_id: str) -> Path:
        try:
            UUID(job_id)
        except (TypeError, ValueError):
            raise RegistrationError("unsafe_state") from None
        workspace = self.workspaces / job_id
        if workspace.is_symlink() or (
            workspace.exists() and not workspace.is_dir()
        ):
            raise RegistrationError("unsafe_state")
        workspace.mkdir(mode=0o700, exist_ok=True)
        workspace.chmod(0o700)
        resolved = workspace.resolve(strict=True)
        try:
            resolved.relative_to(self.workspaces.resolve(strict=True))
        except ValueError:
            raise RegistrationError("unsafe_state") from None
        return resolved


class LocalOps(Protocol):
    def scaffold(self, plan: dict[str, Any], workspace: Path) -> tuple[Path, dict[str, Any]]: ...

    def run_tests(self, project_dir: Path) -> dict[str, Any]: ...

    def build_and_check(self, project_dir: Path) -> tuple[list[Path], dict[str, Any]]: ...

    def verify_public_install(self, plan: dict[str, Any], project_dir: Path) -> dict[str, Any]: ...


class ProviderBackend(Protocol):
    def preflight(self, distribution: str, owner: str) -> dict[str, Any]: ...

    def require_credentials(self, owner: str) -> None: ...

    def upload_initial(
        self, project_dir: Path, distribution: str, version: str, artifacts: list[Path]
    ) -> dict[str, Any]: ...

    def read_release(self, distribution: str, version: str) -> dict[str, Any]: ...

    def create_repository(
        self, owner: str, repository: str, visibility: str, description: str
    ) -> dict[str, Any]: ...

    def push_source(
        self, project_dir: Path, owner: str, repository: str, branch: str
    ) -> dict[str, Any]: ...

    def add_active_publisher(
        self,
        distribution: str,
        owner: str,
        repository: str,
        workflow_filename: str,
    ) -> dict[str, Any]: ...

    def read_repository(
        self, owner: str, repository: str, visibility: str, branch: str
    ) -> dict[str, Any]: ...

    def apply_public_protection(self, owner: str, repository: str, branch: str) -> dict[str, Any]: ...


class BoundedRunner:
    """Fixed-argv subprocess runner with bounded time and retained output."""

    def __init__(self, *, timeout: float = 300.0, output_limit: int = MAX_COMMAND_OUTPUT):
        self.timeout = timeout
        self.output_limit = output_limit

    def __call__(
        self, args: list[str], cwd: Path, env: dict[str, str] | None = None
    ) -> CommandResult:
        if (
            not isinstance(args, list)
            or not args
            or not all(isinstance(item, str) for item in args)
        ):
            raise PyPICommandError("Invalid fixed command invocation.")
        try:
            with tempfile.TemporaryFile(dir=str(cwd)) as stdout_file, tempfile.TemporaryFile(
                dir=str(cwd)
            ) as stderr_file:
                process = subprocess.Popen(
                    args,
                    cwd=str(cwd),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    shell=False,
                    start_new_session=os.name == "posix",
                )
                try:
                    returncode = process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    try:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:  # pragma: no cover - supported service host is Linux.
                            process.kill()
                    except ProcessLookupError:
                        pass
                    process.wait()
                    raise TimeoutError("Bounded command timed out.") from None
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read(self.output_limit + 1)
                stderr = stderr_file.read(self.output_limit + 1)
        except OSError:
            raise PyPICommandError("Fixed command could not be started.") from None

        def decode(value: bytes) -> str:
            clipped = value[: self.output_limit]
            return clipped.decode("utf-8", errors="replace")

        return CommandResult(
            args=list(args),
            returncode=returncode,
            stdout=decode(stdout),
            stderr=decode(stderr),
        )


class DefaultLocalOps:
    def __init__(self, config: ServiceConfig, runner: BoundedRunner | None = None):
        self.config = config
        self.runner = runner or BoundedRunner(timeout=config.command_timeout)

    @staticmethod
    def _command_env(project_dir: Path) -> dict[str, str]:
        workspace = project_dir.parent
        temp_dir = _private_subdirectory(workspace, "tmp")
        cache_dir = _private_subdirectory(workspace, "cache")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(workspace),
            "TMPDIR": str(temp_dir),
            "XDG_CACHE_HOME": str(cache_dir),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
        }
        for key in ("LANG", "LC_ALL", "TZ", "VIRTUAL_ENV"):
            value = os.environ.get(key)
            if value:
                env[key] = value
        return env

    def scaffold(self, plan: dict[str, Any], workspace: Path) -> tuple[Path, dict[str, Any]]:
        project_dir = workspace / "project"
        result = scaffold_package(
            plan["distribution"],
            project_dir,
            initial_version=plan["initial_version"],
            description=plan["description"],
            requires_python=plan["requires_python"],
            template="chatarch",
            include_mkdocs=True,
            include_workflows=True,
            include_chatenv_provider=False,
        )
        return result.project_dir, {
            "module_name": result.module_name,
            "file_count": len(result.created_files),
        }

    @staticmethod
    def _require_success(result: CommandResult) -> None:
        if result.returncode != 0:
            raise PyPICommandError("Fixed local validation command failed.")

    def run_tests(self, project_dir: Path) -> dict[str, Any]:
        result = self.runner(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            project_dir,
            env=self._command_env(project_dir),
        )
        self._require_success(result)
        return {"passed": True}

    def build_and_check(self, project_dir: Path) -> tuple[list[Path], dict[str, Any]]:
        command_env = self._command_env(project_dir)

        def isolated_runner(args, cwd):
            return self.runner(args, cwd, env=command_env)

        _build_result, artifacts = build_package(
            project_dir,
            clean=True,
            no_isolation=True,
            runner=isolated_runner,
        )
        check_distributions(project_dir, strict=True, runner=isolated_runner)
        return artifacts, {"artifacts": [path.name for path in artifacts]}

    def verify_public_install(self, plan: dict[str, Any], project_dir: Path) -> dict[str, Any]:
        """Resolve the public package by name before repository creation."""
        workspace = project_dir.parent
        venv_dir = _private_subdirectory(workspace, "public-install")
        env = self._command_env(project_dir)
        env.pop("PIP_NO_INDEX", None)
        env.pop("VIRTUAL_ENV", None)
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        self._require_success(self.runner(
            [sys.executable, "-m", "venv", str(venv_dir)], workspace, env=env
        ))
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        requirement = f"{plan['distribution']}=={plan['initial_version']}"
        install = [str(python), "-m", "pip", "--isolated", "install", "--no-cache-dir",
            "--only-binary=:all:", "--index-url", "https://pypi.org/simple", requirement]
        for attempt in range(3):
            result = self.runner(install, workspace, env=env)
            if result.returncode == 0:
                break
            if attempt == 2:
                self._require_success(result)
            time.sleep(2.0)
        code = (
            "import importlib,importlib.metadata,inspect,sys;"
            "m=importlib.import_module(sys.argv[2]);"
            "assert importlib.metadata.version(sys.argv[1])==sys.argv[3];"
            "assert 'site-packages' in inspect.getfile(m)"
        )
        self._require_success(self.runner(
            [str(python), "-I", "-c", code, plan["distribution"], plan["module_name"], plan["initial_version"]],
            workspace, env=env,
        ))
        cli = venv_dir / ("Scripts" if os.name == "nt" else "bin") / plan["module_name"]
        version = self.runner([str(cli), "--version"], workspace, env=env)
        self._require_success(version)
        if plan["initial_version"] not in version.stdout:
            raise PyPICommandError("Public package version could not be verified.")
        tree = self.runner([str(cli), "--tree"], workspace, env=env)
        self._require_success(tree)
        if plan["module_name"] not in tree.stdout or "--help" not in tree.stdout:
            raise PyPICommandError("Public package CLI tree could not be verified.")
        return {"installed": True, "version": plan["initial_version"], "cli_tree": True}


class DefaultProviderBackend:
    """Production adapters; all provider writes are one-shot and read back."""

    def __init__(self, config: ServiceConfig, runner: BoundedRunner | None = None):
        self.config = config
        self.runner = runner or BoundedRunner(timeout=config.command_timeout)

    def _pypi_values(self) -> dict[str, str]:
        values = load_active_pypi_env(self.config.chatarch_home)
        for key in ("PYPI_API_TOKEN", "PYPI_USERNAME"):
            if os.getenv(key):
                values[key] = os.environ[key]
        return values

    def _github_token(self) -> str | None:
        try:
            from chatgh.config import GitHubConfig
        except ImportError:
            return None
        values = EnvStore(get_paths(self.config.chatarch_home).envs_dir).load_active(
            GitHubConfig
        )
        return os.getenv("GITHUB_ACCESS_TOKEN") or values.get("GITHUB_ACCESS_TOKEN")

    def _session_payload(self) -> dict[str, Any]:
        payload = load_session_payload_from_env(home=self.config.chatarch_home)
        base_url = str(payload.get("base_url") or "https://pypi.org").rstrip("/")
        if base_url != "https://pypi.org":
            raise PyPISessionError(
                "Registration service requires an official PyPI session."
            )
        return payload

    def preflight(self, distribution: str, owner: str) -> dict[str, Any]:
        registry_status = "unknown"
        ownership = "unknown"
        try:
            checks = check_repository_conflicts(
                distribution, timeout=min(self.config.provider_timeout, 10.0)
            )
            registry_status = (
                "occupied" if any(item.status == "fail" for item in checks) else "available"
            )
            ownership = "not_applicable" if registry_status == "available" else "unknown"
        except Exception:
            registry_status = "unknown"

        pypi_values = self._pypi_values()
        upload_status = "ready" if pypi_values.get("PYPI_API_TOKEN") else "needs_auth"
        session_status = "needs_auth"
        projects: list[str] = []
        try:
            payload = self._session_payload()
            validate_session_payload(payload, timeout=self.config.provider_timeout)
            session_status = "ready"
            if registry_status == "occupied":
                project_payload = list_projects_from_payload(
                    payload, timeout=self.config.provider_timeout
                )
                projects = [str(item) for item in project_payload.get("projects") or []]
        except Exception as exc:
            session_status = (
                "needs_auth"
                if isinstance(exc, PyPISessionError)
                and getattr(exc, "category", "session") != "network"
                else "unknown"
            )
        if registry_status == "occupied" and session_status == "ready":
            target = normalize_distribution_name(distribution)
            ownership = (
                "owned"
                if any(normalize_distribution_name(item) == target for item in projects)
                else "not_owned"
            )

        github_status = "needs_auth"
        github_identity = None
        repository_status = "unknown"
        github_token = self._github_token()
        if github_token:
            try:
                from chatgh.github.api import credential_path_from_repo, get_client
                from chatgh.github.requests import get_repo_optional_payload

                full_name = f"{owner}/{distribution}"
                client = get_client(
                    github_token,
                    require_token=True,
                    credential_path=credential_path_from_repo(full_name),
                )
                github_identity = str(client.get_user().login)
                existing = get_repo_optional_payload(full_name, github_token)
                repository_status = "exists" if existing is not None else "absent"
                github_status = "ready"
            except Exception as exc:
                github_status = (
                    "needs_auth"
                    if getattr(exc, "status", None) in {401, 403}
                    else "unknown"
                )

        return {
            "registry_status": registry_status,
            "ownership": ownership,
            "repository_status": repository_status,
            "pypi_upload_status": upload_status,
            "pypi_session_status": session_status,
            "github_status": github_status,
            "github_identity": github_identity,
        }

    def require_credentials(self, owner: str) -> None:
        del owner
        if not self._pypi_values().get("PYPI_API_TOKEN") or not self._github_token():
            raise RegistrationError("needs_auth")
        try:
            self._session_payload()
        except PyPISessionError:
            raise RegistrationError("needs_auth") from None

    def upload_initial(
        self, project_dir: Path, distribution: str, version: str, artifacts: list[Path]
    ) -> dict[str, Any]:
        if version != INITIAL_VERSION:
            raise RegistrationError("invalid_request")
        del distribution, artifacts
        token = self._pypi_values().get("PYPI_API_TOKEN")
        if not token:
            raise RegistrationError("needs_auth")
        upload_home = _private_subdirectory(project_dir.parent, "upload-home")
        upload_temp = _private_subdirectory(project_dir.parent, "upload-tmp")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(upload_home),
            "TMPDIR": str(upload_temp),
            "XDG_CONFIG_HOME": str(upload_home),
            "PYTHONNOUSERSITE": "1",
        }
        for key in (
            "LANG",
            "LC_ALL",
            "TZ",
            "VIRTUAL_ENV",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
        ):
            value = os.environ.get(key)
            if value:
                env[key] = value
        env.update(
            {
                "TWINE_USERNAME": "__token__",
                "TWINE_PASSWORD": token,
                "TWINE_NON_INTERACTIVE": "1",
                "TWINE_CONFIG_FILE": os.devnull,
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            }
        )
        upload_distributions(
            project_dir,
            repository_url="https://upload.pypi.org/legacy/",
            username="__token__",
            env=env,
            runner=self.runner,
            non_interactive=True,
        )
        return {"uploaded": True}

    def read_release(self, distribution: str, version: str) -> dict[str, Any]:
        url = (
            "https://pypi.org/pypi/"
            f"{urllib_parse.quote(distribution, safe='')}/"
            f"{urllib_parse.quote(version, safe='')}/json"
        )
        last_payload: dict[str, Any] | None = None
        for attempt in range(6):
            request = urllib_request.Request(url, headers={"Accept": "application/json"})
            try:
                with urllib_request.urlopen(
                    request, timeout=self.config.provider_timeout
                ) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError("oversized provider response")
                    parsed = json.loads(raw.decode("utf-8"))
                    if isinstance(parsed, dict):
                        last_payload = parsed
            except (urllib_error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
                last_payload = None
            if last_payload is not None:
                info = last_payload.get("info") or {}
                urls = last_payload.get("urls") or []
                wheel = any(
                    item.get("packagetype") == "bdist_wheel"
                    for item in urls
                    if isinstance(item, dict)
                )
                sdist = any(
                    item.get("packagetype") == "sdist"
                    for item in urls
                    if isinstance(item, dict)
                )
                if str(info.get("version")) == version and wheel and sdist:
                    return {
                        "version": version,
                        "wheel": True,
                        "sdist": True,
                        "url": (
                            "https://pypi.org/project/"
                            f"{urllib_parse.quote(distribution)}/"
                            f"{urllib_parse.quote(version)}/"
                        ),
                    }
            if attempt < 5:
                time.sleep(2.0)
        raise RuntimeError("PyPI release readback was not verified.")

    def create_repository(
        self, owner: str, repository: str, visibility: str, description: str
    ) -> dict[str, Any]:
        token = self._github_token()
        if not token:
            raise RegistrationError("needs_auth")
        from chatgh.github.commands import create_repo

        payload = create_repo(
            owner,
            repository,
            visibility == "private",
            description,
            "error",
            token,
        )
        return {
            "created": payload.get("created") is True,
            "url": f"https://github.com/{owner}/{repository}",
        }

    @staticmethod
    def _require_git_success(result: CommandResult) -> None:
        if result.returncode != 0:
            raise RuntimeError("Fixed git operation failed.")

    def push_source(
        self, project_dir: Path, owner: str, repository: str, branch: str
    ) -> dict[str, Any]:
        token = self._github_token()
        if not token:
            raise RegistrationError("needs_auth")
        from chatgh.github.api import github_auth_extraheader

        url = f"https://github.com/{owner}/{repository}.git"
        git_home = _private_subdirectory(project_dir.parent, "git-home")
        git_temp = _private_subdirectory(project_dir.parent, "git-tmp")
        git_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(git_home),
            "TMPDIR": str(git_temp),
        }
        for key in (
            "LANG",
            "LC_ALL",
            "TZ",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
            "SSL_CERT_FILE",
        ):
            value = os.environ.get(key)
            if value:
                git_env[key] = value
        git_env.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        commands = (
            ["git", "init", "--template=", "--initial-branch", branch],
            ["git", "config", "user.name", "ChatPyPI Registration Service"],
            ["git", "config", "user.email", "noreply@chatarch.invalid"],
            ["git", "add", "--all"],
            ["git", "commit", "--message", "Initial package scaffold"],
            ["git", "remote", "add", "origin", url],
        )
        for args in commands:
            self._require_git_success(
                self.runner(list(args), project_dir, env=git_env)
            )
        push_env = dict(git_env)
        push_env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": f"http.{url}.extraHeader",
                "GIT_CONFIG_VALUE_0": github_auth_extraheader(token),
            }
        )
        self._require_git_success(
            self.runner(
                ["git", "push", "--set-upstream", "origin", branch],
                project_dir,
                env=push_env,
            )
        )
        return {"branch": branch, "pushed": True}

    def add_active_publisher(
        self,
        distribution: str,
        owner: str,
        repository: str,
        workflow_filename: str,
    ) -> dict[str, Any]:
        payload = self._session_payload()
        result = add_github_publisher_to_project_from_payload(
            payload,
            distribution,
            owner=owner,
            repository=repository,
            workflow=workflow_filename,
            environment=None,
            timeout=self.config.provider_timeout,
        )
        return {"active": result.get("ok") is True, "workflow": workflow_filename}

    @staticmethod
    def _protection_policy_matches(data: dict[str, Any]) -> bool:
        reviews = data.get("required_pull_request_reviews")
        return (
            isinstance(reviews, dict)
            and type(reviews.get("required_approving_review_count")) is int
            and reviews["required_approving_review_count"] == 0
            and isinstance(data.get("enforce_admins"), dict)
            and data["enforce_admins"].get("enabled") is True
            and isinstance(data.get("allow_force_pushes"), dict)
            and data["allow_force_pushes"].get("enabled") is False
            and isinstance(data.get("allow_deletions"), dict)
            and data["allow_deletions"].get("enabled") is False
        )

    def apply_public_protection(self, owner: str, repository: str, branch: str) -> dict[str, Any]:
        from chatgh.github.api import get_client

        token = self._github_token()
        if not token:
            raise RegistrationError("needs_auth")
        target = get_client(token, require_token=True).get_repo(f"{owner}/{repository}").get_branch(branch)
        target.edit_protection(
            enforce_admins=True, required_approving_review_count=0,
            dismiss_stale_reviews=False, require_code_owner_reviews=False,
            allow_force_pushes=False, allow_deletions=False,
        )
        data = target.get_protection().raw_data
        return {"verified": self._protection_policy_matches(data)}

    def _read_protection_policy(self, owner: str, repository: str, branch: str) -> dict[str, Any]:
        from chatgh.github.api import get_client

        token = self._github_token()
        if not token:
            raise RegistrationError("needs_auth")
        return get_client(token, require_token=True).get_repo(f"{owner}/{repository}").get_branch(branch).get_protection().raw_data

    def read_repository(
        self, owner: str, repository: str, visibility: str, branch: str
    ) -> dict[str, Any]:
        token = self._github_token()
        if not token:
            raise RegistrationError("needs_auth")
        from chatgh.github.commands import inspect_repo_protection, view_repo

        full_name = f"{owner}/{repository}"
        last_result: dict[str, Any] | None = None
        for attempt in range(5):
            try:
                repo = view_repo(full_name, token)
                protection = inspect_repo_protection(full_name, token)
            except Exception:
                if attempt == 4:
                    raise RuntimeError(
                        "GitHub repository readback could not be verified."
                    ) from None
                time.sleep(2.0)
                continue
            protected = protection.get("default_branch_protected")
            complete = not protection.get("errors") and protected in {True, False}
            policy_verified = False
            if visibility == "public":
                data = self._read_protection_policy(owner, repository, branch)
                policy_verified = self._protection_policy_matches(data)
                complete = complete and protected is True and policy_verified
            last_result = {
                "visibility": repo.get("visibility"),
                "default_branch": repo.get("default_branch"),
                "default_branch_protected": protected,
                "readback_complete": complete,
                "protection_policy_verified": policy_verified,
                "url": f"https://github.com/{owner}/{repository}",
            }
            if (
                complete
                and last_result["visibility"] == visibility
                and last_result["default_branch"] == branch
            ):
                return last_result
            if attempt < 4:
                time.sleep(2.0)
        assert last_result is not None
        return last_result


class RegistrationManager:
    """Plan, submit, execute, and inspect registration-only jobs."""

    def __init__(
        self,
        config: ServiceConfig,
        *,
        backend: ProviderBackend | None = None,
        local_ops: LocalOps | None = None,
        start_executor: bool = True,
    ):
        self.config = validate_service_config(config)
        self.store = RegistrationStore(config)
        self.store.recover_interrupted()
        self.backend = backend or DefaultProviderBackend(config)
        self.local_ops = local_ops or DefaultLocalOps(config)
        self._executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="chatpypi-registration")
            if start_executor
            else None
        )
        self._workflow_lock = threading.Lock()
        self._closed = False

    def __enter__(self) -> "RegistrationManager":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._executor is not None:
                self._executor.shutdown(wait=True, cancel_futures=False)
        finally:
            self.store.close()

    def capabilities(self) -> dict[str, Any]:
        return {
            "service": "chatpypi-registration",
            "api_version": "v1",
            "mode": "registration-only",
            "completion_state": "registered",
            "registration_enabled": self.config.registration_enabled,
            "stages": list(REGISTRATION_STAGES),
            "constraints": {
                "initial_version": INITIAL_VERSION,
                "template": "chatarch",
                "default_visibility": "private",
                "public_requires_explicit_plan_field": True,
                "automatic_release": False,
                "automatic_mutation_replay": False,
            },
        }

    def _preflight_item(self, distribution: str, owner: str) -> dict[str, Any]:
        distribution, normalized, module = _validate_distribution(distribution)
        try:
            result = self.backend.preflight(distribution, owner)
        except Exception:
            result = {
                "registry_status": "unknown",
                "ownership": "unknown",
                "repository_status": "unknown",
                "pypi_upload_status": "unknown",
                "pypi_session_status": "unknown",
                "github_status": "unknown",
                "github_identity": None,
            }
        allowed_status = {"available", "occupied", "unknown"}
        registry_status = result.get("registry_status", "unknown")
        if registry_status not in allowed_status:
            registry_status = "unknown"
        repository_status = result.get("repository_status", "unknown")
        if repository_status not in {"absent", "exists", "unknown"}:
            repository_status = "unknown"
        credential_statuses = {
            key: result.get(key, "unknown")
            if result.get(key, "unknown") in {"ready", "needs_auth", "unknown"}
            else "unknown"
            for key in (
                "pypi_upload_status",
                "pypi_session_status",
                "github_status",
            )
        }
        ownership = result.get("ownership", "unknown")
        if ownership not in {"owned", "not_owned", "unknown", "not_applicable"}:
            ownership = "unknown"
        github_identity = result.get("github_identity")
        if not isinstance(github_identity, str) or not _OWNER_RE.fullmatch(
            github_identity
        ):
            github_identity = None
            if credential_statuses["github_status"] == "ready":
                credential_statuses["github_status"] = "unknown"
                repository_status = "unknown"
        blockers: list[str] = []
        if registry_status != "available":
            blockers.append(
                "target_unavailable"
                if registry_status == "occupied"
                else "preflight_unknown"
            )
        if repository_status == "exists":
            blockers.append("target_unavailable")
        elif (
            repository_status == "unknown"
            and credential_statuses["github_status"] != "needs_auth"
        ):
            blockers.append("preflight_unknown")
        if any(status == "needs_auth" for status in credential_statuses.values()):
            blockers.append("needs_auth")
        if any(status == "unknown" for status in credential_statuses.values()):
            blockers.append("preflight_unknown")
        return {
            "distribution": distribution,
            "normalized_name": normalized,
            "module_name": module,
            "registry": {
                "status": registry_status,
                "ownership": ownership,
            },
            "repository": {"status": repository_status},
            "credentials": {
                "pypi_upload": credential_statuses["pypi_upload_status"],
                "pypi_session": credential_statuses["pypi_session_status"],
                "github": credential_statuses["github_status"],
            },
            "github_identity": github_identity,
            "can_plan": registry_status == "available"
            and repository_status in {"absent", "unknown"}
            and not any(item == "preflight_unknown" for item in blockers),
            "blockers": list(dict.fromkeys(blockers)),
        }

    def preflight(self, names: list[str], owner: str) -> dict[str, Any]:
        owner = _validated_owner(owner, self.config.allowed_owners)
        if not isinstance(names, list) or not 1 <= len(names) <= MAX_PREFLIGHT_NAMES:
            raise RegistrationError("invalid_request")
        items = [self._preflight_item(name, owner) for name in names]
        normalized = [item["normalized_name"] for item in items]
        if len(set(normalized)) != len(normalized):
            raise RegistrationError("invalid_request")
        return {
            "owner": owner,
            "items": items,
            "count": len(items),
            "read_only": True,
        }

    def create_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = _validate_plan_request(payload, self.config)
        item = self.preflight([request["distribution"]], request["owner"])["items"][0]
        if item["registry"]["status"] != "available":
            raise RegistrationError(
                "preflight_unknown"
                if item["registry"]["status"] == "unknown"
                else "target_unavailable"
            )
        if item["repository"]["status"] == "exists":
            raise RegistrationError("target_unavailable")
        if item["repository"]["status"] == "unknown" and "needs_auth" not in item["blockers"]:
            raise RegistrationError("preflight_unknown")
        if "preflight_unknown" in item["blockers"]:
            raise RegistrationError("preflight_unknown")

        created_at = _utc_now()
        plan_id = str(uuid4())
        confirmation = (
            f"register:{request['normalized_name']}:{request['owner']}/"
            f"{request['distribution']}:{request['visibility']}:{INITIAL_VERSION}"
        )
        plan: dict[str, Any] = {
            "id": plan_id,
            "created_at": created_at,
            "distribution": request["distribution"],
            "normalized_name": request["normalized_name"],
            "module_name": request["module_name"],
            "description": request["description"],
            "owner": request["owner"],
            "repository": request["distribution"],
            "visibility": request["visibility"],
            "initial_version": INITIAL_VERSION,
            "requires_python": ">=3.10",
            "template": "chatarch",
            "default_branch": DEFAULT_BRANCH,
            "workflow_filename": PUBLISH_WORKFLOW,
            "stages": [stage for stage in REGISTRATION_STAGES if stage != "public_protection" or request["visibility"] == "public"],
            "confirmation": confirmation,
            "ready": not item["blockers"],
            "blockers": item["blockers"],
        }
        plan["digest"] = hashlib.sha256(_canonical_json(plan).encode("utf-8")).hexdigest()
        self.store.save_plan(plan)
        return plan

    def submit_job(
        self, plan_id: str, confirmation: str, idempotency_key: str
    ) -> tuple[dict[str, Any], bool]:
        if not self.config.registration_enabled:
            raise RegistrationError("registration_disabled")
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
            idempotency_key
        ):
            raise RegistrationError("invalid_request")
        plan = self.store.get_plan(_validate_uuid(plan_id))
        if not isinstance(confirmation, str) or confirmation != plan["confirmation"]:
            raise RegistrationError("confirmation_mismatch")
        job, replay = self.store.create_job(
            plan=plan,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            max_queue=self.config.max_queue,
        )
        if not replay and self._executor is not None:
            self._executor.submit(self.run_job, job["id"])
        return job, replay

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.store.get_job(_validate_uuid(job_id))

    def list_jobs(self, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise RegistrationError("invalid_request")
        if not isinstance(offset, int) or not 0 <= offset <= 10000:
            raise RegistrationError("invalid_request")
        return self.store.list_jobs(limit=limit, offset=offset)

    def _stage(self, job_id: str, stage: str) -> None:
        self.store.set_stage(job_id, stage)

    def _receipt(self, job_id: str, stage: str, data: dict[str, Any]) -> None:
        self.store.append_receipt(job_id, stage, data)

    @staticmethod
    def _external_write(call):
        try:
            return call()
        except RegistrationError as exc:
            if exc.category == "needs_auth":
                raise
            raise _ReconciliationRequired() from None
        except Exception:
            raise _ReconciliationRequired() from None

    def _assert_project_path(self, workspace: Path, project_dir: Path) -> Path:
        if project_dir.is_symlink() or not project_dir.is_dir():
            raise RegistrationError("unsafe_state")
        resolved = project_dir.resolve(strict=True)
        try:
            resolved.relative_to(workspace.resolve(strict=True))
        except ValueError:
            raise RegistrationError("unsafe_state") from None
        return resolved

    def _assert_artifacts(self, project_dir: Path, artifacts: list[Path]) -> list[Path]:
        if not artifacts:
            raise RegistrationError("local_execution")
        dist_dir = (project_dir / "dist").resolve(strict=True)
        try:
            dist_dir.relative_to(project_dir)
        except ValueError:
            raise RegistrationError("unsafe_state") from None
        resolved: list[Path] = []
        for artifact in artifacts:
            path = Path(artifact)
            if path.is_symlink() or not path.is_file():
                raise RegistrationError("unsafe_state")
            candidate = path.resolve(strict=True)
            try:
                candidate.relative_to(dist_dir)
            except ValueError:
                raise RegistrationError("unsafe_state") from None
            if len(candidate.name) > 255 or any(
                ord(char) < 32 or ord(char) == 127 for char in candidate.name
            ):
                raise RegistrationError("unsafe_state")
            resolved.append(candidate)
        return resolved

    @staticmethod
    def _harden_private_tree(root: Path) -> None:
        if root.is_symlink() or not root.is_dir():
            raise RegistrationError("unsafe_state")
        root.chmod(0o700)
        for current, directory_names, file_names in os.walk(
            root, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            current_path.chmod(0o700)
            for name in directory_names:
                directory = current_path / name
                if directory.is_symlink():
                    raise RegistrationError("unsafe_state")
                directory.chmod(0o700)
            for name in file_names:
                file_path = current_path / name
                if file_path.is_symlink() or not file_path.is_file():
                    raise RegistrationError("unsafe_state")
                file_path.chmod(0o600)

    def run_job(self, job_id: str) -> None:
        with self._workflow_lock:
            self._execute_job(job_id)

    def _execute_job(self, job_id: str) -> None:
        external_write_started = False
        external_mutation_completed = False
        try:
            job = self.store.get_job(job_id)
            if job["status"] != "queued":
                return
            plan = self.store.get_plan(job["plan_id"])
            self.store.set_running(job_id, "credentials")

            self.backend.require_credentials(plan["owner"])
            self._receipt(job_id, "credentials", {"ready": True})

            self._stage(job_id, "preflight")
            check = self.backend.preflight(plan["distribution"], plan["owner"])
            credentials = (
                check.get("pypi_upload_status"),
                check.get("pypi_session_status"),
                check.get("github_status"),
            )
            if any(status == "needs_auth" for status in credentials):
                raise RegistrationError("needs_auth")
            if any(status != "ready" for status in credentials):
                raise RegistrationError("preflight_unknown")
            if (
                check.get("registry_status") == "unknown"
                or check.get("repository_status") == "unknown"
            ):
                raise RegistrationError("preflight_unknown")
            if (
                check.get("registry_status") != "available"
                or check.get("repository_status") != "absent"
            ):
                raise RegistrationError("target_unavailable")
            self._receipt(
                job_id,
                "preflight",
                {"registry": "available", "repository": "absent"},
            )

            workspace = self.store.workspace_for(job_id)
            self._stage(job_id, "scaffold")
            try:
                project_dir, scaffold = self.local_ops.scaffold(plan, workspace)
            finally:
                self._harden_private_tree(workspace)
            project_dir = self._assert_project_path(workspace, Path(project_dir))
            self._receipt(
                job_id,
                "scaffold",
                {
                    "module_name": plan["module_name"],
                    "file_count": int(scaffold.get("file_count", 0)),
                },
            )

            self._stage(job_id, "tests")
            try:
                self.local_ops.run_tests(project_dir)
            finally:
                self._harden_private_tree(workspace)
            self._receipt(job_id, "tests", {"passed": True})

            self._stage(job_id, "build_check")
            try:
                artifacts, _build = self.local_ops.build_and_check(project_dir)
            finally:
                self._harden_private_tree(workspace)
            artifacts = self._assert_artifacts(project_dir, artifacts)
            self._receipt(
                job_id,
                "build_check",
                {"artifacts": sorted(path.name for path in artifacts)},
            )

            self._stage(job_id, "pypi_upload")
            external_write_started = True
            self._external_write(
                lambda: self.backend.upload_initial(
                    project_dir,
                    plan["distribution"],
                    plan["initial_version"],
                    artifacts,
                )
            )
            external_mutation_completed = True
            self._receipt(
                job_id,
                "pypi_upload",
                {"initial_version": plan["initial_version"], "artifact_count": len(artifacts)},
            )

            self._stage(job_id, "pypi_readback")
            try:
                release = self.backend.read_release(
                    plan["distribution"], plan["initial_version"]
                )
            except Exception:
                raise _ReconciliationRequired() from None
            if (
                release.get("version") != plan["initial_version"]
                or release.get("wheel") is not True
                or release.get("sdist") is not True
            ):
                raise _ReconciliationRequired()
            self._receipt(
                job_id,
                "pypi_readback",
                {
                    "version": plan["initial_version"],
                    "wheel": True,
                    "sdist": True,
                    "url": (
                        "https://pypi.org/project/"
                        f"{urllib_parse.quote(plan['distribution'])}/"
                        f"{plan['initial_version']}/"
                    ),
                },
            )

            self._stage(job_id, "public_install")
            installed = self.local_ops.verify_public_install(plan, project_dir)
            if installed.get("installed") is not True or installed.get("version") != plan["initial_version"] or installed.get("cli_tree") is not True:
                raise _ReconciliationRequired()
            self._receipt(job_id, "public_install", installed)

            self._stage(job_id, "github_repository")
            created = self._external_write(
                lambda: self.backend.create_repository(
                    plan["owner"],
                    plan["repository"],
                    plan["visibility"],
                    plan["description"],
                )
            )
            if created.get("created") is not True:
                raise _ReconciliationRequired()
            github_url = f"https://github.com/{plan['owner']}/{plan['repository']}"
            self._receipt(
                job_id,
                "github_repository",
                {"created": True, "visibility": plan["visibility"], "url": github_url},
            )

            self._stage(job_id, "source_push")
            try:
                self._external_write(
                    lambda: self.backend.push_source(
                        project_dir,
                        plan["owner"],
                        plan["repository"],
                        plan["default_branch"],
                    )
                )
            finally:
                self._harden_private_tree(workspace)
            self._receipt(
                job_id,
                "source_push",
                {"branch": plan["default_branch"], "pushed": True},
            )

            if plan["visibility"] == "public":
                self._stage(job_id, "public_protection")
                governance = self._external_write(lambda: self.backend.apply_public_protection(
                    plan["owner"], plan["repository"], plan["default_branch"]
                ))
                if governance.get("verified") is not True:
                    raise _ReconciliationRequired()
                self._receipt(job_id, "public_protection", {"verified": True})

            self._stage(job_id, "trusted_publisher")
            publisher = self._external_write(
                lambda: self.backend.add_active_publisher(
                    plan["distribution"],
                    plan["owner"],
                    plan["repository"],
                    plan["workflow_filename"],
                )
            )
            if publisher.get("active") is not True:
                raise _ReconciliationRequired()
            self._receipt(
                job_id,
                "trusted_publisher",
                {"active": True, "workflow": plan["workflow_filename"]},
            )

            self._stage(job_id, "github_readback")
            try:
                repository = self.backend.read_repository(
                    plan["owner"],
                    plan["repository"],
                    plan["visibility"],
                    plan["default_branch"],
                )
            except Exception:
                raise _ReconciliationRequired() from None
            if (
                repository.get("readback_complete") is not True
                or repository.get("visibility") != plan["visibility"]
                or repository.get("default_branch") != plan["default_branch"]
            ):
                raise _ReconciliationRequired()
            protected = repository.get("default_branch_protected")
            if protected not in {True, False}:
                raise _ReconciliationRequired()
            if plan["visibility"] == "public" and (protected is not True or repository.get("protection_policy_verified") is not True):
                raise _ReconciliationRequired()
            self._receipt(
                job_id,
                "github_readback",
                {
                    "visibility": plan["visibility"],
                    "default_branch": plan["default_branch"],
                    "default_branch_protected": protected,
                    "url": github_url,
                },
            )
            self._harden_private_tree(workspace)
            self.store.set_terminal(job_id, "registered")
        except RegistrationError as exc:
            if external_write_started and (
                exc.category != "needs_auth" or external_mutation_completed
            ):
                status = "reconciliation_required"
                category = "external_outcome_unknown"
            else:
                status = (
                    "blocked"
                    if exc.category
                    in {"needs_auth", "preflight_unknown", "target_unavailable"}
                    else "failed"
                )
                category = exc.category
            try:
                self.store.set_terminal(job_id, status, category)
            except RegistrationError:
                pass
        except _ReconciliationRequired:
            try:
                self.store.set_terminal(
                    job_id, "reconciliation_required", "external_outcome_unknown"
                )
            except RegistrationError:
                pass
        except Exception:
            try:
                if external_write_started:
                    self.store.set_terminal(
                        job_id,
                        "reconciliation_required",
                        "external_outcome_unknown",
                    )
                else:
                    self.store.set_terminal(job_id, "failed", "local_execution")
            except RegistrationError:
                pass


__all__ = [
    "BoundedRunner",
    "DefaultLocalOps",
    "DefaultProviderBackend",
    "INITIAL_VERSION",
    "REGISTRATION_STAGES",
    "RegistrationError",
    "RegistrationManager",
    "ServiceConfig",
    "load_service_config",
    "normalize_distribution_name",
    "registration_paths",
    "validate_service_config",
]
