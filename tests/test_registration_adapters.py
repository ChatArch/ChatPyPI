from __future__ import annotations

import os
from pathlib import Path
import sys

from chatpypi.main import CommandResult, RepositoryCheck, ScaffoldResult
from chatpypi.registration import (
    BoundedRunner,
    DefaultLocalOps,
    DefaultProviderBackend,
    ServiceConfig,
)


def _config(tmp_path: Path) -> ServiceConfig:
    home = tmp_path / "home"
    return ServiceConfig(
        api_token="test-service-token",
        host="127.0.0.1",
        port=8765,
        allowed_hosts=("testserver",),
        allowed_owners=("ChatArch",),
        registration_enabled=True,
        chatarch_home=home,
        state_dir=home / "runtime" / "chatpypi" / "registration-api",
    )


def test_default_preflight_is_read_only_and_uses_importable_chatgh(monkeypatch, tmp_path):
    backend = DefaultProviderBackend(_config(tmp_path))
    monkeypatch.setattr(
        "chatpypi.registration.check_repository_conflicts",
        lambda *_args, **_kwargs: [
            RepositoryCheck("package name", "ok", "available")
        ],
    )
    monkeypatch.setattr(
        backend, "_pypi_values", lambda: {"PYPI_API_TOKEN": "opaque-test-value"}
    )
    monkeypatch.setattr(backend, "_session_payload", lambda: {"cookies": []})
    monkeypatch.setattr(
        "chatpypi.registration.validate_session_payload",
        lambda *_args, **_kwargs: {"authenticated": True},
    )
    monkeypatch.setattr(backend, "_github_token", lambda: "opaque-test-value")

    class User:
        login = "api-worker"

    class Client:
        def get_user(self):
            return User()

    monkeypatch.setattr("chatgh.github.api.get_client", lambda *_args, **_kwargs: Client())
    monkeypatch.setattr(
        "chatgh.github.requests.get_repo_optional_payload",
        lambda *_args, **_kwargs: None,
    )

    result = backend.preflight("demo-pkg", "ChatArch")

    assert result == {
        "registry_status": "available",
        "ownership": "not_applicable",
        "repository_status": "absent",
        "pypi_upload_status": "ready",
        "pypi_session_status": "ready",
        "github_status": "ready",
        "github_identity": "api-worker",
    }


def test_default_local_ops_reuse_scaffold_build_check_and_fixed_pytest(
    monkeypatch, tmp_path
):
    commands = []

    def runner(args, cwd, env=None):
        commands.append((list(args), cwd, env))
        return CommandResult(list(args), 0, "", "")

    local = DefaultLocalOps(_config(tmp_path), runner=runner)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project = workspace / "project"
    scaffold_calls = []

    def fake_scaffold(distribution, project_dir, **kwargs):
        project_dir.mkdir()
        created = project_dir / "pyproject.toml"
        created.write_text("[project]\n", encoding="utf-8")
        scaffold_calls.append((distribution, project_dir, kwargs))
        return ScaffoldResult(project_dir, distribution, "demo_pkg", [created])

    wheel = project / "dist" / "demo_pkg-0.1.0-py3-none-any.whl"
    build_calls = []

    def fake_build(project_dir, **kwargs):
        wheel.parent.mkdir()
        wheel.write_bytes(b"wheel")
        build_calls.append((project_dir, kwargs))
        return CommandResult([], 0, "", ""), [wheel]

    check_calls = []

    def fake_check(project_dir, **kwargs):
        check_calls.append((project_dir, kwargs))
        return CommandResult([], 0, "", ""), [wheel]

    monkeypatch.setattr("chatpypi.registration.scaffold_package", fake_scaffold)
    monkeypatch.setattr("chatpypi.registration.build_package", fake_build)
    monkeypatch.setattr("chatpypi.registration.check_distributions", fake_check)
    plan = {
        "distribution": "demo-pkg",
        "module_name": "demo_pkg",
        "initial_version": "0.1.0",
        "description": "A small package",
        "requires_python": ">=3.10",
    }

    project_dir, scaffold_receipt = local.scaffold(plan, workspace)
    test_receipt = local.run_tests(project_dir)
    artifacts, _build_receipt = local.build_and_check(project_dir)

    assert scaffold_receipt == {"module_name": "demo_pkg", "file_count": 1}
    assert scaffold_calls[0][2]["template"] == "chatarch"
    assert commands[0][0] == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    assert commands[0][1] == project
    assert commands[0][2]["HOME"] == str(workspace)
    assert commands[0][2]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert "PYPI_API_TOKEN" not in commands[0][2]
    assert test_receipt == {"passed": True}
    assert artifacts == [wheel]
    assert scaffold_calls[0][2]["requires_python"] == ">=3.10"
    assert build_calls[0][0] == project
    assert build_calls[0][1]["clean"] is True
    assert build_calls[0][1]["no_isolation"] is True
    assert callable(build_calls[0][1]["runner"])
    assert check_calls[0][0] == project
    assert check_calls[0][1]["strict"] is True
    assert callable(check_calls[0][1]["runner"])


def test_bounded_runner_caps_retained_output_and_uses_fixed_argv(tmp_path):
    runner = BoundedRunner(timeout=5.0, output_limit=64)

    result = runner(
        [sys.executable, "-c", "print('x' * 1000)"],
        tmp_path,
    )

    assert result.returncode == 0
    assert result.args[:2] == [sys.executable, "-c"]
    assert len(result.stdout.encode("utf-8")) <= 64
    assert result.stderr == ""


def test_default_local_ops_real_scaffold_and_tests_stay_in_tmp(tmp_path):
    local = DefaultLocalOps(_config(tmp_path))
    workspace = tmp_path / "job-workspace"
    workspace.mkdir(mode=0o700)
    plan = {
        "distribution": "local-registration-demo",
        "module_name": "local_registration_demo",
        "initial_version": "0.1.0",
        "description": "Local registration adapter smoke",
        "requires_python": ">=3.10",
    }

    project, receipt = local.scaffold(plan, workspace)
    test_receipt = local.run_tests(project)

    assert receipt["module_name"] == "local_registration_demo"
    assert (project / "pyproject.toml").is_file()
    assert test_receipt == {"passed": True}
    assert not (project / ".pytest_cache").exists()


def test_initial_upload_is_noninteractive_and_does_not_return_secret(
    monkeypatch, tmp_path
):
    backend = DefaultProviderBackend(_config(tmp_path))
    monkeypatch.setattr(
        backend, "_pypi_values", lambda: {"PYPI_API_TOKEN": "opaque-test-value"}
    )
    captured = {}

    def fake_upload(project_dir, **kwargs):
        captured.update({"project_dir": project_dir, **kwargs})
        return CommandResult([], 0, "", ""), []

    monkeypatch.setattr("chatpypi.registration.upload_distributions", fake_upload)
    project = tmp_path / "project"
    project.mkdir()

    result = backend.upload_initial(project, "demo-pkg", "0.1.0", [])

    assert result == {"uploaded": True}
    assert captured["username"] == "__token__"
    assert captured["repository_url"] == "https://upload.pypi.org/legacy/"
    assert captured["non_interactive"] is True
    assert captured["env"]["TWINE_NON_INTERACTIVE"] == "1"
    assert captured["env"]["TWINE_CONFIG_FILE"] == os.devnull
    assert "GITHUB_ACCESS_TOKEN" not in captured["env"]
    assert "CHATPYPI_API_TOKEN" not in captured["env"]
    assert "opaque-test-value" not in str(result)


def test_repository_create_uses_chatgh_api_with_selected_visibility(
    monkeypatch, tmp_path
):
    backend = DefaultProviderBackend(_config(tmp_path))
    monkeypatch.setattr(backend, "_github_token", lambda: "opaque-test-value")
    calls = []

    def fake_create(owner, name, private, description, if_exists, token):
        calls.append((owner, name, private, description, if_exists, token))
        return {"created": True}

    monkeypatch.setattr("chatgh.github.commands.create_repo", fake_create)

    result = backend.create_repository(
        "ChatArch", "demo-pkg", "public", "A small package"
    )

    assert result == {
        "created": True,
        "url": "https://github.com/ChatArch/demo-pkg",
    }
    assert calls == [
        (
            "ChatArch",
            "demo-pkg",
            False,
            "A small package",
            "error",
            "opaque-test-value",
        )
    ]


def test_source_push_uses_only_fixed_git_argv_and_env_auth(monkeypatch, tmp_path):
    calls = []

    def runner(args, cwd, env=None):
        calls.append((list(args), cwd, env))
        return CommandResult(list(args), 0, "", "")

    backend = DefaultProviderBackend(_config(tmp_path), runner=runner)
    monkeypatch.setattr(backend, "_github_token", lambda: "opaque-test-value")
    project = tmp_path / "project"
    project.mkdir()

    result = backend.push_source(project, "ChatArch", "demo-pkg", "main")

    assert result == {"branch": "main", "pushed": True}
    assert calls[-1][0] == ["git", "push", "--set-upstream", "origin", "main"]
    assert calls[-1][2]["GIT_TERMINAL_PROMPT"] == "0"
    assert calls[-1][2]["GIT_CONFIG_NOSYSTEM"] == "1"
    assert "PYPI_API_TOKEN" not in calls[-1][2]
    assert "CHATPYPI_API_TOKEN" not in calls[-1][2]
    assert all(env is not None for _args, _cwd, env in calls)
    assert all("opaque-test-value" not in " ".join(args) for args, _cwd, _env in calls)
    assert all(args[0] == "git" for args, _cwd, _env in calls)


def test_active_publisher_and_repository_readback_are_importable_calls(
    monkeypatch, tmp_path
):
    backend = DefaultProviderBackend(_config(tmp_path))
    monkeypatch.setattr(backend, "_session_payload", lambda: {"cookies": []})
    monkeypatch.setattr(backend, "_github_token", lambda: "opaque-test-value")
    publisher_calls = []

    def fake_publisher(payload, project, **kwargs):
        publisher_calls.append((payload, project, kwargs))
        return {"ok": True}

    monkeypatch.setattr(
        "chatpypi.registration.add_github_publisher_to_project_from_payload",
        fake_publisher,
    )
    monkeypatch.setattr(
        "chatgh.github.commands.view_repo",
        lambda *_args: {"visibility": "public", "default_branch": "main"},
    )
    monkeypatch.setattr(
        "chatgh.github.commands.inspect_repo_protection",
        lambda *_args: {
            "default_branch_protected": True,
            "errors": [],
        },
    )

    publisher = backend.add_active_publisher(
        "demo-pkg", "ChatArch", "demo-pkg", "publish.yml"
    )
    repository = backend.read_repository(
        "ChatArch", "demo-pkg", "public", "main"
    )

    assert publisher == {"active": True, "workflow": "publish.yml"}
    assert publisher_calls[0][2] == {
        "owner": "ChatArch",
        "repository": "demo-pkg",
        "workflow": "publish.yml",
        "environment": None,
        "timeout": 20.0,
    }
    assert repository == {
        "visibility": "public",
        "default_branch": "main",
        "default_branch_protected": True,
        "readback_complete": True,
        "url": "https://github.com/ChatArch/demo-pkg",
    }
