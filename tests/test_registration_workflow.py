from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import time

import pytest
from chatenv.paths import get_paths
from chatenv.store import EnvStore

from chatpypi.config import RegistrationAPIConfig
from chatpypi.registration import (
    RegistrationError,
    RegistrationManager,
    ServiceConfig,
    load_service_config,
    normalize_distribution_name,
    validate_service_config,
)


class FakeLocalOps:
    def __init__(self, events: list[str]):
        self.events = events

    def scaffold(self, plan: dict, workspace: Path) -> tuple[Path, dict]:
        self.events.append("scaffold")
        project_dir = workspace / "project"
        project_dir.mkdir()
        return project_dir, {"module_name": plan["module_name"], "file_count": 4}

    def run_tests(self, project_dir: Path) -> dict:
        self.events.append("tests")
        return {"passed": True}

    def build_and_check(self, project_dir: Path) -> tuple[list[Path], dict]:
        self.events.append("build_check")
        dist = project_dir / "dist"
        dist.mkdir()
        wheel = dist / "demo_pkg-0.1.0-py3-none-any.whl"
        sdist = dist / "demo_pkg-0.1.0.tar.gz"
        wheel.write_bytes(b"wheel")
        sdist.write_bytes(b"sdist")
        return [wheel, sdist], {"artifacts": [wheel.name, sdist.name]}


class FakeBackend:
    def __init__(self, events: list[str], *, auth_ready: bool = True):
        self.events = events
        self.auth_ready = auth_ready
        self.create_calls = 0
        self.timeout_on_create = False

    def preflight(self, distribution: str, owner: str) -> dict:
        self.events.append("preflight")
        auth = "ready" if self.auth_ready else "needs_auth"
        return {
            "registry_status": "available",
            "ownership": "not_applicable",
            "repository_status": "absent",
            "pypi_upload_status": auth,
            "pypi_session_status": auth,
            "github_status": auth,
            "github_identity": "api-worker" if self.auth_ready else None,
        }

    def require_credentials(self, owner: str) -> None:
        self.events.append("credentials")
        if not self.auth_ready:
            raise RegistrationError("needs_auth")

    def upload_initial(
        self, project_dir: Path, distribution: str, version: str, artifacts: list[Path]
    ) -> dict:
        self.events.append("upload")
        return {"uploaded": True}

    def read_release(self, distribution: str, version: str) -> dict:
        self.events.append("pypi_readback")
        return {
            "version": version,
            "wheel": True,
            "sdist": True,
            "url": f"https://pypi.org/project/{distribution}/{version}/",
        }

    def create_repository(
        self, owner: str, repository: str, visibility: str, description: str
    ) -> dict:
        self.events.append("github_create")
        self.create_calls += 1
        if self.timeout_on_create:
            raise TimeoutError("provider timeout with unsafe detail")
        return {"created": True, "url": f"https://github.com/{owner}/{repository}"}

    def push_source(
        self, project_dir: Path, owner: str, repository: str, branch: str
    ) -> dict:
        self.events.append("push")
        return {"branch": branch, "pushed": True}

    def add_active_publisher(
        self,
        distribution: str,
        owner: str,
        repository: str,
        workflow_filename: str,
    ) -> dict:
        self.events.append("publisher")
        return {"active": True, "workflow": workflow_filename}

    def read_repository(
        self, owner: str, repository: str, visibility: str, branch: str
    ) -> dict:
        self.events.append("github_readback")
        return {
            "visibility": visibility,
            "default_branch": branch,
            "default_branch_protected": False,
            "readback_complete": True,
            "url": f"https://github.com/{owner}/{repository}",
        }


def _config(tmp_path: Path, *, enabled: bool = True) -> ServiceConfig:
    home = tmp_path / "chatarch-home"
    return ServiceConfig(
        api_token="test-service-token",
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver", "127.0.0.1", "localhost"),
        allowed_owners=("ChatArch",),
        registration_enabled=enabled,
        chatarch_home=home,
        state_dir=home / "runtime" / "chatpypi" / "registration-api",
    )


def _request(name: str = "Demo_Pkg", *, visibility: str = "private") -> dict:
    return {
        "distribution": name,
        "description": "A small package",
        "owner": "ChatArch",
        "visibility": visibility,
    }


def test_name_normalization_and_python_module_validation(tmp_path):
    assert normalize_distribution_name(" Demo_Pkg...tools ") == "demo-pkg-tools"
    manager = RegistrationManager(
        _config(tmp_path),
        backend=FakeBackend([]),
        local_ops=FakeLocalOps([]),
        start_executor=False,
    )
    try:
        with pytest.raises(RegistrationError) as exc_info:
            manager.create_plan(_request("class"))
        assert exc_info.value.category == "invalid_request"
    finally:
        manager.close()


def test_typed_service_config_defaults_to_loopback_and_read_only(monkeypatch, tmp_path):
    home = tmp_path / "home"
    for key in RegistrationAPIConfig.get_fields().values():
        monkeypatch.delenv(key.env_key, raising=False)
    EnvStore(get_paths(home).envs_dir).save_active(
        RegistrationAPIConfig,
        {"CHATPYPI_API_TOKEN": "placeholder-service-value"},
    )

    config = load_service_config(home)

    assert config.host == "127.0.0.1"
    assert config.registration_enabled is False
    assert config.allowed_owners == ("ChatArch",)
    assert config.state_dir.is_relative_to(home)

    with pytest.raises(RegistrationError) as exc_info:
        validate_service_config(replace(config, allowed_hosts=("*",)))
    assert exc_info.value.category == "invalid_request"


def test_plan_confirmation_idempotency_and_normalized_name_exclusion(tmp_path):
    events: list[str] = []
    manager = RegistrationManager(
        _config(tmp_path),
        backend=FakeBackend(events),
        local_ops=FakeLocalOps(events),
        start_executor=False,
    )
    try:
        plan = manager.create_plan(_request())
        assert plan["normalized_name"] == "demo-pkg"
        assert plan["module_name"] == "demo_pkg"
        assert plan["initial_version"] == "0.1.0"
        assert plan["visibility"] == "private"
        assert plan["confirmation"].startswith("register:demo-pkg:")
        plan["description"] = "caller-side mutation"
        assert manager.store.get_plan(plan["id"])["description"] == "A small package"
        plan = manager.store.get_plan(plan["id"])

        with pytest.raises(RegistrationError) as exc_info:
            manager.submit_job(plan["id"], "wrong target", "idem-confirmation-0001")
        assert exc_info.value.category == "confirmation_mismatch"

        job, replay = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-0001"
        )
        assert replay is False
        same, replay = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-0001"
        )
        assert replay is True
        assert same["id"] == job["id"]

        with pytest.raises(RegistrationError) as exc_info:
            manager.submit_job(
                plan["id"], plan["confirmation"], "idem-registration-0002"
            )
        assert exc_info.value.category == "target_busy"
    finally:
        manager.close()


def test_registration_workflow_orders_readback_before_github_and_ends_registered(tmp_path):
    events: list[str] = []
    manager = RegistrationManager(
        _config(tmp_path),
        backend=FakeBackend(events),
        local_ops=FakeLocalOps(events),
        start_executor=False,
    )
    try:
        plan = manager.create_plan(_request(visibility="public"))
        job, _ = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-0003"
        )
        events.clear()
        manager.run_job(job["id"])
        completed = manager.get_job(job["id"])

        assert completed["status"] == "registered"
        assert events == [
            "credentials",
            "preflight",
            "scaffold",
            "tests",
            "build_check",
            "upload",
            "pypi_readback",
            "github_create",
            "push",
            "publisher",
            "github_readback",
        ]
        assert all("unsafe detail" not in str(item) for item in completed["receipts"])
        workspace = manager.store.workspaces / job["id"]
        artifact = workspace / "project" / "dist" / "demo_pkg-0.1.0.tar.gz"
        assert os.stat(workspace / "project").st_mode & 0o777 == 0o700
        assert os.stat(artifact).st_mode & 0o777 == 0o600
    finally:
        manager.close()


def test_missing_auth_blocks_without_local_or_external_mutation(tmp_path):
    events: list[str] = []
    backend = FakeBackend(events, auth_ready=False)
    manager = RegistrationManager(
        _config(tmp_path), backend=backend, local_ops=FakeLocalOps(events), start_executor=False
    )
    try:
        plan = manager.create_plan(_request())
        job, _ = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-0004"
        )
        events.clear()
        manager.run_job(job["id"])
        blocked = manager.get_job(job["id"])
        assert blocked["status"] == "blocked"
        assert blocked["stage"] == "credentials"
        assert blocked["error"] == {
            "category": "needs_auth",
            "message": "Required provider authentication is unavailable or invalid.",
        }
        assert events == ["credentials"]
    finally:
        manager.close()


def test_external_mutation_timeout_requires_reconciliation_and_is_not_retried(tmp_path):
    events: list[str] = []
    backend = FakeBackend(events)
    backend.timeout_on_create = True
    manager = RegistrationManager(
        _config(tmp_path), backend=backend, local_ops=FakeLocalOps(events), start_executor=False
    )
    try:
        plan = manager.create_plan(_request())
        job, _ = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-0005"
        )
        manager.run_job(job["id"])
        uncertain = manager.get_job(job["id"])
        assert uncertain["status"] == "reconciliation_required"
        assert uncertain["stage"] == "github_repository"
        assert uncertain["error"]["category"] == "external_outcome_unknown"
        assert "unsafe detail" not in str(uncertain)
        assert backend.create_calls == 1
    finally:
        manager.close()


def test_post_upload_receipt_failure_is_reconciliation_not_safe_retry(
    monkeypatch, tmp_path
):
    events: list[str] = []
    manager = RegistrationManager(
        _config(tmp_path),
        backend=FakeBackend(events),
        local_ops=FakeLocalOps(events),
        start_executor=False,
    )
    try:
        plan = manager.create_plan(_request("receipt-demo"))
        job, _ = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-receipt"
        )
        original = manager.store.append_receipt

        def fail_after_upload(job_id, stage, data):
            if stage == "pypi_upload":
                raise RegistrationError("unsafe_state")
            return original(job_id, stage, data)

        monkeypatch.setattr(manager.store, "append_receipt", fail_after_upload)
        manager.run_job(job["id"])

        uncertain = manager.get_job(job["id"])
        assert uncertain["status"] == "reconciliation_required"
        assert uncertain["stage"] == "pypi_upload"
        assert events.count("upload") == 1
    finally:
        manager.close()


def test_auth_loss_after_upload_requires_reconciliation(tmp_path):
    events: list[str] = []

    class ExpiringBackend(FakeBackend):
        def add_active_publisher(self, *args, **kwargs):
            self.events.append("publisher")
            raise RegistrationError("needs_auth")

    manager = RegistrationManager(
        _config(tmp_path),
        backend=ExpiringBackend(events),
        local_ops=FakeLocalOps(events),
        start_executor=False,
    )
    try:
        plan = manager.create_plan(_request("auth-loss-demo"))
        job, _ = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-auth-loss"
        )
        manager.run_job(job["id"])

        uncertain = manager.get_job(job["id"])
        assert uncertain["status"] == "reconciliation_required"
        assert uncertain["stage"] == "trusted_publisher"
        assert uncertain["error"]["category"] == "external_outcome_unknown"
    finally:
        manager.close()


def test_restart_marks_interrupted_job_for_reconciliation_without_replay(tmp_path):
    config = _config(tmp_path)
    first = RegistrationManager(
        config, backend=FakeBackend([]), local_ops=FakeLocalOps([]), start_executor=False
    )
    plan = first.create_plan(_request())
    job, _ = first.submit_job(
        plan["id"], plan["confirmation"], "idem-registration-0006"
    )
    first.close()

    second_backend = FakeBackend([])
    second = RegistrationManager(
        config, backend=second_backend, local_ops=FakeLocalOps([]), start_executor=False
    )
    try:
        recovered = second.get_job(job["id"])
        assert recovered["status"] == "reconciliation_required"
        assert recovered["error"]["category"] == "interrupted"
        assert second_backend.create_calls == 0
    finally:
        second.close()


def test_state_permissions_and_symlink_state_rejection(tmp_path):
    config = _config(tmp_path)
    manager = RegistrationManager(
        config, backend=FakeBackend([]), local_ops=FakeLocalOps([]), start_executor=False
    )
    manager.close()
    assert os.stat(config.state_dir).st_mode & 0o777 == 0o700
    assert os.stat(config.state_dir / "registration.sqlite3").st_mode & 0o777 == 0o600
    assert os.stat(config.state_dir / "executor.lock").st_mode & 0o777 == 0o600

    target = tmp_path / "outside"
    target.mkdir()
    link = config.chatarch_home / "linked-state"
    link.symlink_to(target, target_is_directory=True)
    bad = ServiceConfig(**{**config.__dict__, "state_dir": link})
    with pytest.raises(RegistrationError) as exc_info:
        RegistrationManager(
            bad, backend=FakeBackend([]), local_ops=FakeLocalOps([]), start_executor=False
        )
    assert exc_info.value.category == "unsafe_state"


def test_state_lock_allows_only_one_executor_owner(tmp_path):
    config = _config(tmp_path)
    first = RegistrationManager(
        config, backend=FakeBackend([]), local_ops=FakeLocalOps([]), start_executor=False
    )
    try:
        with pytest.raises(RegistrationError) as exc_info:
            RegistrationManager(
                config,
                backend=FakeBackend([]),
                local_ops=FakeLocalOps([]),
                start_executor=False,
            )
        assert exc_info.value.category == "executor_locked"
    finally:
        first.close()

    replacement = RegistrationManager(
        config, backend=FakeBackend([]), local_ops=FakeLocalOps([]), start_executor=False
    )
    replacement.close()


def test_single_writer_executor_completes_mocked_job_asynchronously(tmp_path):
    events: list[str] = []
    manager = RegistrationManager(
        _config(tmp_path),
        backend=FakeBackend(events),
        local_ops=FakeLocalOps(events),
        start_executor=True,
    )
    try:
        plan = manager.create_plan(_request("async-demo"))
        job, _ = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-async-01"
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            current = manager.get_job(job["id"])
            if current["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        assert manager.get_job(job["id"])["status"] == "registered"
    finally:
        manager.close()


def test_unknown_second_preflight_blocks_before_local_work(tmp_path):
    events: list[str] = []

    class UnknownBackend(FakeBackend):
        unknown = False

        def preflight(self, distribution: str, owner: str) -> dict:
            result = super().preflight(distribution, owner)
            if self.unknown:
                result.update(
                    {
                        "repository_status": "unknown",
                        "github_status": "unknown",
                    }
                )
            return result

    backend = UnknownBackend(events)
    manager = RegistrationManager(
        _config(tmp_path), backend=backend, local_ops=FakeLocalOps(events), start_executor=False
    )
    try:
        plan = manager.create_plan(_request("unknown-demo"))
        job, _ = manager.submit_job(
            plan["id"], plan["confirmation"], "idem-registration-unknown"
        )
        backend.unknown = True
        events.clear()
        manager.run_job(job["id"])
        blocked = manager.get_job(job["id"])
        assert blocked["status"] == "blocked"
        assert blocked["error"]["category"] == "preflight_unknown"
        assert events == ["credentials", "preflight"]
    finally:
        manager.close()


def test_occupied_name_never_creates_plan_or_runs_upload(tmp_path):
    events: list[str] = []

    class OccupiedBackend(FakeBackend):
        def preflight(self, distribution: str, owner: str) -> dict:
            result = super().preflight(distribution, owner)
            result.update({"registry_status": "occupied", "ownership": "owned"})
            return result

    manager = RegistrationManager(
        _config(tmp_path),
        backend=OccupiedBackend(events),
        local_ops=FakeLocalOps(events),
        start_executor=False,
    )
    try:
        with pytest.raises(RegistrationError) as exc_info:
            manager.create_plan(_request("occupied-demo"))
        assert exc_info.value.category == "target_unavailable"
        assert "upload" not in events
    finally:
        manager.close()
