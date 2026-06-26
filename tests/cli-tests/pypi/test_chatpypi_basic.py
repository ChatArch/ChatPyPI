from pathlib import Path
import json

import pytest
from click.testing import CliRunner
import subprocess
import sys
import os

from chatpypi.cli import cli
from chatpypi.session_ops import encode_session_token


pytestmark = [pytest.mark.e2e]


def _write_minimal_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "demo-pkg"
version = "0.1.0"
readme = "README.md"
requires-python = ">=3.9"
license = {text = "MIT"}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT\n", encoding="utf-8")


def _pythonpath_with_fake_site(fake_site: Path) -> str:
    current = os.environ.get("PYTHONPATH")
    if current:
        return f"{fake_site}{os.pathsep}{current}"
    return str(fake_site)


def _write_fake_build_module(fake_site: Path) -> None:
    build_pkg = fake_site / "build"
    build_pkg.mkdir(parents=True, exist_ok=True)
    (build_pkg / "__init__.py").write_text("", encoding="utf-8")
    (build_pkg / "__main__.py").write_text(
        """
from pathlib import Path
import sys


def main() -> int:
    args = sys.argv[1:]
    outdir = Path(args[args.index("--outdir") + 1])
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "demo_pkg-0.1.0-py3-none-any.whl").write_text("wheel", encoding="utf-8")
    (outdir / "demo_pkg-0.1.0.tar.gz").write_text("sdist", encoding="utf-8")
    print("fake build ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_fake_twine_module(fake_site: Path) -> None:
    twine_pkg = fake_site / "twine"
    twine_pkg.mkdir(parents=True, exist_ok=True)
    (twine_pkg / "__init__.py").write_text("", encoding="utf-8")
    (twine_pkg / "__main__.py").write_text(
        """
import os
import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        print("fake check ok")
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "upload":
        print("fake upload ok")
        print("args=" + " ".join(sys.argv[1:]))
        print("username=" + os.environ.get("TWINE_USERNAME", ""))
        print("password=" + os.environ.get("TWINE_PASSWORD", ""))
        return 0
    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_session_file(path: Path) -> None:
    path.write_text(
        """
{
  "provider": "pypi",
  "username": "LooKeng",
  "created_at": "2026-06-26T10:00:00Z",
  "updated_at": "2026-06-26T11:00:00Z",
  "cookies": [
    {"name": "session_id", "value": "masked"}
  ],
  "csrf": {
    "last_seen_token": "masked"
  },
  "meta": {
    "email_verified": true,
    "two_factor_enabled": true
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_chatpypi_basic(tmp_path):
    runner = CliRunner()
    project_dir = tmp_path / "mychat"
    dist_dir = project_dir / "dist"
    fake_site = tmp_path / "fake-site"

    init = runner.invoke(
        cli, ["init", "mychat", "--project-dir", str(project_dir)]
    )
    assert init.exit_code == 0
    assert (project_dir / "src" / "mychat" / "__init__.py").exists()
    assert (project_dir / "tests" / "conftest.py").exists()
    assert "MIT License" in (project_dir / "LICENSE").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.9"' in (project_dir / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    pytest_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr
    assert "1 passed" in pytest_result.stdout

    _write_fake_build_module(fake_site)
    _write_fake_twine_module(fake_site)

    build = runner.invoke(
        cli,
        ["build", "--project-dir", str(project_dir)],
        env={"PYTHONPATH": _pythonpath_with_fake_site(fake_site)},
    )
    assert build.exit_code == 0
    assert (
        f"Building distributions from {project_dir} into {dist_dir}..." in build.output
    )
    assert "Built distributions:" in build.output
    assert "fake build ok" in build.output

    check = runner.invoke(
        cli,
        ["check", "--project-dir", str(project_dir)],
        env={"PYTHONPATH": _pythonpath_with_fake_site(fake_site)},
    )
    assert check.exit_code == 0
    assert "fake check ok" in check.output
    assert "Checked distributions:" in check.output


def test_chatpypi_pkg_upload_uses_token_env(tmp_path):
    runner = CliRunner()
    project_dir = tmp_path / "demo-pkg"
    fake_site = tmp_path / "fake-site"

    _write_minimal_project(project_dir)
    _write_fake_build_module(fake_site)
    _write_fake_twine_module(fake_site)

    build = runner.invoke(
        cli,
        ["pkg", "build", "--project-dir", str(project_dir)],
        env={"PYTHONPATH": _pythonpath_with_fake_site(fake_site)},
    )
    assert build.exit_code == 0

    upload = runner.invoke(
        cli,
        [
            "pkg",
            "upload",
            "--project-dir",
            str(project_dir),
            "--repository",
            "testpypi",
            "--token-env",
            "PYPI_API_TOKEN",
        ],
        env={
            "PYTHONPATH": _pythonpath_with_fake_site(fake_site),
            "PYPI_API_TOKEN": "demo-token-value",
        },
    )

    assert upload.exit_code == 0
    assert "fake upload ok" in upload.output
    assert "--repository testpypi" in upload.output
    assert "--username __token__" in upload.output
    assert "password=[REDACTED]" in upload.output
    assert "demo-token-value" not in upload.output


def test_chatpypi_auth_session_show_uses_env_session_token(tmp_path):
    runner = CliRunner()
    session_file = tmp_path / "pypi-session.json"
    _write_session_file(session_file)
    token = encode_session_token(json.loads(session_file.read_text(encoding="utf-8")))

    result = runner.invoke(
        cli,
        ["auth", "session", "show", "--format", "json"],
        env={"PYPI_SESSION_TOKEN": token},
    )

    assert result.exit_code == 0
    assert '"source": "PYPI_SESSION_TOKEN"' in result.output
    assert '"username": "LooKeng"' in result.output
    assert '"cookie_count": 1' in result.output
    assert '"has_last_seen_csrf": true' in result.output


def test_chatpypi_auth_session_show_rejects_bad_token(tmp_path):
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["auth", "session", "show"],
        env={"PYPI_SESSION_TOKEN": "not-a-valid-token"},
    )

    assert result.exit_code != 0
    assert "PYPI_SESSION_TOKEN is not a valid ChatPyPI session token" in result.output


def test_planned_operational_commands_fail_nonzero():
    result = CliRunner().invoke(cli, ["token", "create"])

    assert result.exit_code != 0
    assert "not implemented yet" in result.output


def test_chatpypi_auth_login_writes_real_session_via_login_helper(tmp_path, monkeypatch):
    env_file = tmp_path / "envs" / "PyPI" / ".env"

    def fake_login(**kwargs):
        assert kwargs["username"] == "LooKeng"
        assert kwargs["password"] == "demo-password"
        assert kwargs["totp_secret"] == "demo-totp"
        payload = {
            "provider": "pypi",
            "username": "LooKeng",
            "created_at": "2026-06-26T10:00:00Z",
            "updated_at": "2026-06-26T10:00:00Z",
            "cookies": [{"name": "session_id", "value": "masked"}],
            "csrf": {"last_seen_token": "masked"},
            "meta": {},
        }
        return payload, encode_session_token(payload)

    monkeypatch.setattr("chatpypi.cli.login_to_pypi", fake_login)
    monkeypatch.setattr("chatpypi.cli.save_active_pypi_env_value", lambda key, value: env_file)

    result = CliRunner().invoke(
        cli,
        [
            "auth",
            "login",
            "--username",
            "LooKeng",
            "--password-env",
            "PYPI_PASSWORD",
            "--totp-env",
            "PYPI_TOTP_SECRET",
            "--format",
            "json",
        ],
        env={"PYPI_PASSWORD": "demo-password", "PYPI_TOTP_SECRET": "demo-totp"},
    )

    assert result.exit_code == 0
    assert '"authenticated": true' in result.output
    assert '"env_key": "PYPI_SESSION_TOKEN"' in result.output
    assert '"username": "LooKeng"' in result.output
    assert "demo-password" not in result.output
    assert "demo-totp" not in result.output


def test_chatpypi_auth_login_env_profile_prefers_profile_values(monkeypatch, tmp_path):
    written = tmp_path / "RexWzh.env"

    def fake_login(**kwargs):
        assert kwargs["username"] == "RexWzh"
        assert kwargs["password"] == "profile-password"
        assert kwargs["totp_secret"] == "profile-totp"
        payload = {
            "provider": "pypi",
            "username": "RexWzh",
            "cookies": [{"name": "session_id", "value": "masked"}],
            "csrf": {"last_seen_token": "masked"},
            "meta": {},
        }
        return payload, encode_session_token(payload)

    monkeypatch.setattr("chatpypi.cli.login_to_pypi", fake_login)
    monkeypatch.setattr(
        "chatpypi.cli.load_pypi_env_profile",
        lambda profile: {
            "PYPI_USERNAME": "RexWzh",
            "PYPI_PASSWORD": "profile-password",
            "PYPI_TOTP_SECRET": "profile-totp",
        },
    )
    monkeypatch.setattr(
        "chatpypi.cli.save_pypi_env_profile_value",
        lambda profile, key, value: written,
    )

    result = CliRunner().invoke(
        cli,
        ["auth", "login", "-e", "RexWzh", "--format", "json"],
        env={
            "PYPI_USERNAME": "ProcessUser",
            "PYPI_PASSWORD": "process-password",
            "PYPI_TOTP_SECRET": "process-totp",
        },
    )

    assert result.exit_code == 0
    assert '"env_profile": "RexWzh"' in result.output
    assert '"username": "RexWzh"' in result.output
    assert "process-password" not in result.output
    assert "profile-password" not in result.output


def test_chatpypi_project_and_publisher_lists_call_real_session_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "chatpypi.cli.list_projects_from_session",
        lambda token, token_env="PYPI_SESSION_TOKEN", env_profile=None: {
            "capability": "session",
            "source_url": "https://pypi.org/manage/projects/",
            "projects": ["chatpypi-demo"],
            "count": 1,
            "empty": False,
        },
    )
    monkeypatch.setattr(
        "chatpypi.cli.list_publishers_from_session",
        lambda token, token_env="PYPI_SESSION_TOKEN", env_profile=None: {
            "capability": "session",
            "source_url": "https://pypi.org/manage/account/publishing/",
            "active_publishers": [
                {"fields": {"Provider": "GitHub", "Repository": "ChatArch/ChatPyPI-Demo"}}
            ],
            "pending_publishers": [],
            "active_count": 1,
            "pending_count": 0,
        },
    )

    project_result = CliRunner().invoke(
        cli,
        ["project", "list", "--format", "json"],
        env={"PYPI_SESSION_TOKEN": "encoded"},
    )
    publisher_result = CliRunner().invoke(
        cli,
        ["publisher", "list", "--format", "json"],
        env={"PYPI_SESSION_TOKEN": "encoded"},
    )
    pending_result = CliRunner().invoke(
        cli,
        ["publisher", "pending-list", "--format", "json"],
        env={"PYPI_SESSION_TOKEN": "encoded"},
    )

    assert project_result.exit_code == 0
    assert '"projects": [' in project_result.output
    assert '"chatpypi-demo"' in project_result.output
    assert publisher_result.exit_code == 0
    assert "ChatArch/ChatPyPI-Demo" in publisher_result.output
    assert pending_result.exit_code == 0
    assert '"pending_publishers": []' in pending_result.output


def test_chatpypi_env_profile_does_not_use_process_session_token(monkeypatch):
    captured = {}

    def fake_list_projects(token, token_env="PYPI_SESSION_TOKEN", env_profile=None):
        captured["token"] = token
        captured["token_env"] = token_env
        captured["env_profile"] = env_profile
        return {
            "capability": "session",
            "source_url": "https://pypi.org/manage/projects/",
            "projects": ["profile-project"],
            "count": 1,
            "empty": False,
        }

    monkeypatch.setattr("chatpypi.cli.list_projects_from_session", fake_list_projects)

    result = CliRunner().invoke(
        cli,
        ["project", "list", "-e", "RexWzh", "--format", "json"],
        env={"PYPI_SESSION_TOKEN": "process-token-should-not-be-used"},
    )

    assert result.exit_code == 0
    assert captured == {
        "token": None,
        "token_env": "PYPI_SESSION_TOKEN",
        "env_profile": "RexWzh",
    }
    assert "profile-project" in result.output


def test_chatpypi_doctor_check_verifies_session_token(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "chatpypi.cli.load_session_payload_from_env",
        lambda token=None, token_env="PYPI_SESSION_TOKEN", env_profile=None: {"cookies": [{"name": "session_id", "value": "masked"}]},
    )
    monkeypatch.setattr(
        "chatpypi.cli.validate_session_payload",
        lambda payload: {
            "source_url": "https://pypi.org/manage/account/",
            "authenticated": True,
        },
    )

    result = CliRunner().invoke(
        cli,
        ["doctor", "check", "--format", "json"],
        env={"PYPI_SESSION_TOKEN": "encoded"},
    )

    assert result.exit_code == 0
    assert '"ok": true' in result.output


def test_chatpypi_pkg_upload_reports_unset_secret_env(tmp_path):
    runner = CliRunner()
    project_dir = tmp_path / "demo-pkg"
    fake_site = tmp_path / "fake-site"

    _write_minimal_project(project_dir)
    _write_fake_build_module(fake_site)
    _write_fake_twine_module(fake_site)

    build = runner.invoke(
        cli,
        ["pkg", "build", "--project-dir", str(project_dir)],
        env={"PYTHONPATH": _pythonpath_with_fake_site(fake_site)},
    )
    assert build.exit_code == 0

    upload = runner.invoke(
        cli,
        [
            "pkg",
            "upload",
            "--project-dir",
            str(project_dir),
            "--token-env",
            "PYPI_API_TOKEN",
        ],
        env={"PYTHONPATH": _pythonpath_with_fake_site(fake_site)},
    )

    assert upload.exit_code != 0
    assert "references unset environment variable or profile key: PYPI_API_TOKEN" in upload.output


def test_chatpypi_init_chatarch_template(tmp_path):
    runner = CliRunner()
    project_dir = tmp_path / "mychat-cli"

    result = runner.invoke(
        cli,
        [
            "init",
            "mychat-cli",
            "-t",
            "chatarch",
            "--project-dir",
            str(project_dir),
        ],
    )

    assert result.exit_code == 0
    assert (project_dir / "DEVELOP.md").exists()
    assert (project_dir / "CHANGELOG.md").exists()
    assert (project_dir / "AGENTS.md").exists()
    assert (project_dir / "src" / "mychat_cli" / "cli.py").exists()
    assert (project_dir / "tests" / "test_cli.py").exists()
    assert (project_dir / "docs" / "index.md").exists()
    assert (project_dir / "docs" / "index.en.md").exists()
    assert (project_dir / "README.en.md").exists()
    assert (project_dir / "mkdocs.yml").exists()
    assert (project_dir / "tests" / "cli-tests" / "README.md").exists()
    assert (project_dir / "tests" / "mock-cli-tests" / "README.md").exists()
    assert (project_dir / "tests" / "code-tests" / "README.md").exists()
    assert (project_dir / ".github" / "workflows" / "ci.yml").exists()
    assert (project_dir / ".github" / "workflows" / "publish.yml").exists()
    assert (project_dir / ".github" / "workflows" / "deploy.yaml").exists()
    assert (project_dir / ".github" / "workflows" / "preview.yaml").exists()
    pyproject_text = (project_dir / "pyproject.toml").read_text(encoding="utf-8")
    assert '"chatstyle>=0.1.0,<0.2.0"' in pyproject_text
    assert '"chatenv>=0.2.0,<0.3.0"' in pyproject_text
    assert 'requires-python = ">=3.10"' in pyproject_text
    assert '[project.entry-points."chatenv.configs"]' in pyproject_text
    assert 'mychat_cli = "mychat_cli.config"' in pyproject_text
    assert 'docs = ["mkdocs' in pyproject_text
    assert 'Homepage = "https://github.com/ChatArch/mychat-cli"' in pyproject_text
    assert 'Repository = "https://github.com/ChatArch/mychat-cli"' in pyproject_text
    assert 'Documentation = "https://ChatArch.github.io/mychat-cli"' in pyproject_text
    workflow_texts = [
        path.read_text(encoding="utf-8")
        for path in sorted((project_dir / ".github" / "workflows").iterdir())
    ]
    assert all('python-version: "3.10"' in text for text in workflow_texts)
    assert all("3.11" not in text for text in workflow_texts)
    publish_text = (project_dir / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    assert 'tags:\n      - "v*"' in publish_text
    assert "contents: read" in publish_text
    assert "id-token: write" in publish_text
    assert "environment: pypi" not in publish_text
    assert "Check tag matches package version" in publish_text
    assert "GITHUB_REF_NAME" in publish_text
    assert "git tag -a" not in publish_text
    assert "python -m twine check dist/*" in publish_text
    assert "pypa/gh-action-pypi-publish@release/v1" in publish_text
    assert "PYPI_API_TOKEN" not in publish_text
    assert "PYPI_TOKEN" not in publish_text
    assert "TWINE_USERNAME" not in publish_text
    assert "TWINE_PASSWORD" not in publish_text
    assert "secrets.PYPI" not in publish_text
    assert "twine upload" not in publish_text
    assert "Publish workflow scaffold only" not in publish_text
    cli_text = (project_dir / "src" / "mychat_cli" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert (project_dir / "src" / "mychat_cli" / "config.py").exists()
    assert "from mychat_cli import __version__" in cli_text
    assert '@click.version_option(__version__, prog_name="mychat_cli")' in cli_text
    assert "from chatstyle import" in cli_text
    assert "CommandSchema" in cli_text
    generated_test_text = (project_dir / "tests" / "test_cli.py").read_text(
        encoding="utf-8"
    )
    assert "test_version_option_reports_package_version" in generated_test_text
    readme_text = (project_dir / "README.md").read_text(encoding="utf-8")
    assert readme_text.startswith('<div align="center">\n')
    assert "\n# mychat-cli\n\n" in readme_text
    assert "\n            # mychat-cli\n" not in readme_text
    assert "img.shields.io/pypi/v/mychat-cli.svg" in readme_text
    assert "https://github.com/ChatArch/mychat-cli/actions/workflows/ci.yml" in readme_text
    assert "actions/workflows/ci.yml/badge.svg" in readme_text
    assert "https://ChatArch.github.io/mychat-cli" in readme_text
    assert "OWNER/REPO" not in readme_text
    assert "docs-mkdocs" in readme_text
    assert "CommandSchema" in readme_text
    config_text = (project_dir / "src" / "mychat_cli" / "config.py").read_text(
        encoding="utf-8"
    )
    assert "class MychatCliConfig(BaseEnvConfig):" in config_text
    assert '_aliases = ["mychat_cli"]' in config_text
    assert '_storage_dir = "MychatCli"' in config_text
    assert "def test(cls) -> None:" in config_text
    assert "Schema loaded; no network test is required." in config_text


def test_chatpypi_init_chatarch_can_skip_optional_files(tmp_path):
    runner = CliRunner()
    project_dir = tmp_path / "mychat-cli"

    result = runner.invoke(
        cli,
        [
            "init",
            "mychat-cli",
            "-t",
            "chatarch",
            "--project-dir",
            str(project_dir),
            "--without-mkdocs",
            "--without-workflows",
        ],
    )

    assert result.exit_code == 0
    assert (project_dir / "src" / "mychat_cli" / "cli.py").exists()
    assert not (project_dir / "mkdocs.yml").exists()
    assert not (project_dir / "docs").exists()
    assert not (project_dir / ".github").exists()
    pyproject_text = (project_dir / "pyproject.toml").read_text(encoding="utf-8")
    assert '"chatstyle>=0.1.0,<0.2.0"' in pyproject_text
    assert '"chatenv>=0.2.0,<0.3.0"' in pyproject_text
    assert '[project.entry-points."chatenv.configs"]' in pyproject_text
    assert 'mychat_cli = "mychat_cli.config"' in pyproject_text
    assert 'docs = ["mkdocs' not in pyproject_text
    assert 'Homepage = "https://github.com/ChatArch/mychat-cli"' in pyproject_text
    assert 'Documentation = "https://ChatArch.github.io/mychat-cli"' not in pyproject_text
    readme_text = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "docs-mkdocs" not in readme_text
    assert "actions/workflows/ci.yml" not in readme_text
