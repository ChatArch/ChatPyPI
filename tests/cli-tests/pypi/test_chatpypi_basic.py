from pathlib import Path
import json

import pytest
from click.testing import CliRunner
import subprocess
import sys
import os

from chatpypi.cli import cli
from chatenv import TokenStore

from chatpypi.session_ops import encode_session_token, save_session_payload_to_token_store


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


def test_chatpypi_auth_session_show_uses_chatenv_token_store(tmp_path, monkeypatch):
    runner = CliRunner()
    session_file = tmp_path / "pypi-session.json"
    _write_session_file(session_file)
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    save_session_payload_to_token_store(json.loads(session_file.read_text(encoding="utf-8")))

    result = runner.invoke(
        cli,
        ["auth", "session", "show", "--format", "json"],
    )

    assert result.exit_code == 0
    assert '"source": "ChatEnv token store"' in result.output
    assert '"username": "LooKeng"' in result.output
    assert '"cookie_count": 1' in result.output
    assert '"has_last_seen_csrf": true' in result.output


def test_chatpypi_auth_session_show_rejects_bad_token_store_payload(tmp_path, monkeypatch):
    runner = CliRunner()
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    TokenStore().write("PyPI", values={"payload": "not-a-session-payload"}, token_type="web_session")

    result = runner.invoke(
        cli,
        ["auth", "session", "show"],
    )

    assert result.exit_code != 0
    assert "PyPI token store payload is not a valid session object" in result.output


def test_planned_operational_commands_fail_nonzero():
    result = CliRunner().invoke(cli, ["token", "create"])

    assert result.exit_code != 0
    assert "not implemented yet" in result.output


def test_chatpypi_auth_login_writes_real_session_via_login_helper(tmp_path, monkeypatch):
    token_file = tmp_path / "home" / "tokens" / "PyPI" / "default.json"
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))

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
    assert '"token_profile": "default"' in result.output
    assert '"username": "LooKeng"' in result.output
    assert token_file.exists()
    assert "demo-password" not in result.output
    assert "demo-totp" not in result.output


def test_chatpypi_auth_login_env_profile_prefers_profile_values(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))

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
    assert '"token_profile": "RexWzh"' in result.output
    assert '"username": "RexWzh"' in result.output
    assert (tmp_path / "home" / "tokens" / "PyPI" / "RexWzh.json").exists()
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
    )
    publisher_result = CliRunner().invoke(
        cli,
        ["publisher", "list", "--format", "json"],
    )
    pending_result = CliRunner().invoke(
        cli,
        ["publisher", "pending-list", "--format", "json"],
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
        lambda token=None, token_env="PYPI_SESSION_TOKEN", env_profile=None, home=None: {"cookies": [{"name": "session_id", "value": "masked"}]},
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
    assert (project_dir / "docs" / "cli-tree.md").exists()
    assert (project_dir / "docs" / "cli-tree.en.md").exists()
    assert (project_dir / "docs" / "capability-map.md").exists()
    assert (project_dir / "docs" / "capability-map.en.md").exists()
    assert (project_dir / "docs" / "interface-tree.md").exists()
    assert not (project_dir / "docs" / "commands.md").exists()
    assert not (project_dir / "docs" / "commands.en.md").exists()
    assert not (project_dir / "docs" / "development-plan.md").exists()
    assert not (project_dir / "docs" / "CNAME").exists()
    assert (project_dir / "README.en.md").exists()
    assert (project_dir / "mkdocs.yml").exists()
    agents_text = (project_dir / "AGENTS.md").read_text(encoding="utf-8")
    assert "local `.env`" in agents_text
    assert "project-local skills" in agents_text
    assert "MkDocs navigation should stay grouped" in agents_text
    assert "The CLI tree page is the command entry point" in agents_text
    assert "PyPI Trusted Publisher/OIDC" in agents_text
    assert (project_dir / "tests" / "cli-tests" / "README.md").exists()
    assert (project_dir / "tests" / "mock-cli-tests" / "README.md").exists()
    assert (project_dir / "tests" / "code-tests" / "README.md").exists()
    assert (project_dir / ".github" / "workflows" / "ci.yml").exists()
    assert (project_dir / ".github" / "workflows" / "publish.yml").exists()
    assert (project_dir / ".github" / "workflows" / "deploy.yaml").exists()
    assert (project_dir / ".github" / "workflows" / "preview.yaml").exists()
    assert "site/" in (project_dir / ".gitignore").read_text(encoding="utf-8")
    pyproject_text = (project_dir / "pyproject.toml").read_text(encoding="utf-8")
    assert '"chatstyle>=0.2.0,<0.3.0"' in pyproject_text
    assert '"chatenv>=0.2.11,<0.3.0"' in pyproject_text
    assert 'requires-python = ">=3.10"' in pyproject_text
    assert '[project.entry-points."chatenv.configs"]' in pyproject_text
    assert 'mychat_cli = "mychat_cli.config"' in pyproject_text
    assert (
        'docs = ["mkdocs>=1.6,<2.0", "mkdocs-material>=9.5,<9.7", '
        '"mkdocs-static-i18n>=1.2,<2.0", "mike>=2.0,<3.0"]'
    ) in pyproject_text
    assert 'Homepage = "https://github.com/ChatArch/mychat-cli"' in pyproject_text
    assert 'Repository = "https://github.com/ChatArch/mychat-cli"' in pyproject_text
    assert 'Documentation = "https://arch.gh.wzhecnu.cn/mychat-cli/"' in pyproject_text
    workflow_texts = [
        path.read_text(encoding="utf-8")
        for path in sorted((project_dir / ".github" / "workflows").iterdir())
    ]
    assert all('python-version: "3.10"' in text for text in workflow_texts)
    assert all("3.11" not in text for text in workflow_texts)
    ci_text = (project_dir / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "python -m mychat_cli.cli --version" in ci_text
    assert "python -m mychat_cli.cli --tree" in ci_text
    assert "python -m mychat_cli.cli --tree-brief" in ci_text
    preview_text = (project_dir / ".github" / "workflows" / "preview.yaml").read_text(
        encoding="utf-8"
    )
    assert "git fetch origin gh-pages --depth=1 || true" in preview_text
    assert "mike deploy dev --push --update-aliases --allow-empty" in preview_text
    assert "Path(\"mkdocs.yml\")" in preview_text
    assert "CHATARCH_PREVIEW_URL" in preview_text
    assert "https://arch.gh.wzhecnu.cn/${" + "repo}/dev/" not in preview_text
    assert "https://arch.gh.wzhecnu.cn/${" + "repo.repo}/dev/" not in preview_text
    assert ("github" + ".io") not in preview_text
    mkdocs_text = (project_dir / "mkdocs.yml").read_text(encoding="utf-8")
    assert "- i18n:" in mkdocs_text
    assert "docs_structure: suffix" in mkdocs_text
    assert "fallback_to_default: true" in mkdocs_text
    assert "pymdownx.emoji:" in mkdocs_text
    assert "material.extensions.emoji.twemoji" in mkdocs_text
    assert "material.extensions.emoji.to_svg" in mkdocs_text
    assert "navigation.tabs" in mkdocs_text
    assert "- attr_list" in mkdocs_text
    assert "- md_in_html" in mkdocs_text
    assert "- 命令与接口:" in mkdocs_text
    assert "CLI / API" not in mkdocs_text
    assert "CLI 树: cli-tree.md" in mkdocs_text
    assert "能力地图: capability-map.md" in mkdocs_text
    assert "link: /mychat-cli/en/" in mkdocs_text
    assert "路线图" not in mkdocs_text
    assert "development-plan" not in mkdocs_text
    cli_tree_text = (project_dir / "docs" / "cli-tree.md").read_text(encoding="utf-8")
    assert "# CLI 能力地图" in cli_tree_text
    assert "## 顶层命令" in cli_tree_text
    assert "## 业务命令槽位" in cli_tree_text
    assert "像 ChatTea 的 CLI 树一样" in cli_tree_text
    assert "├── --help" in cli_tree_text
    assert "├── --version" in cli_tree_text
    assert "├── --tree" in cli_tree_text
    assert "└── --tree-brief" in cli_tree_text
    assert "默认树保留参数签名" in cli_tree_text
    capability_text = (project_dir / "docs" / "capability-map.md").read_text(encoding="utf-8")
    assert "# 能力地图" in capability_text
    assert "不生成计划类占位页" in capability_text
    assert "可 import 的 Python 函数" in (project_dir / "docs" / "interface-tree.md").read_text(encoding="utf-8")
    publish_text = (project_dir / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow" + "_dispatch:" not in publish_text
    assert 'tags:\n      - "v*"' in publish_text
    assert "contents: read" in publish_text
    assert "id-token: write" in publish_text
    assert "environment: pypi" not in publish_text
    assert "Verify tag matches package version" in publish_text
    assert "if: github.event_name == 'push'" not in publish_text
    assert "GITHUB_REF_NAME" in publish_text
    assert "git fetch --no-tags origin main:refs/remotes/origin/main" in publish_text
    assert "git merge-base --is-ancestor \"${GITHUB_SHA}\" refs/remotes/origin/main" in publish_text
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
    assert "from chatstyle import add_tree_option" in cli_text
    assert '@click.version_option(__version__, prog_name="mychat_cli")' in cli_text
    assert '@add_tree_option(renderer_options={"root_name": "mychat_cli"})' in cli_text
    assert "_render_cli_tree" not in cli_text
    assert "HELLO_SCHEMA" not in cli_text
    assert "def hello" not in cli_text
    assert "Hello, ChatArch" not in cli_text
    generated_test_text = (project_dir / "tests" / "test_cli.py").read_text(
        encoding="utf-8"
    )
    assert "test_version_option_reports_package_version" in generated_test_text
    assert "test_help_lists_shared_tree_options" in generated_test_text
    assert "test_tree_option_prints_registered_cli_tree" in generated_test_text
    assert "test_tree_brief_option_prints_registered_cli_tree" in generated_test_text
    assert '"--tree-brief"' in generated_test_text
    assert "test_hello" not in generated_test_text
    assert "Hello, ChatArch" not in generated_test_text
    generated_pytest = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated_pytest.returncode == 0, (
        generated_pytest.stdout + generated_pytest.stderr
    )
    readme_text = (project_dir / "README.md").read_text(encoding="utf-8")
    assert readme_text.startswith('<div align="center">\n')
    assert "\n# mychat-cli\n\n" in readme_text
    assert "\n            # mychat-cli\n" not in readme_text
    assert "img.shields.io/pypi/v/mychat-cli.svg" in readme_text
    assert "https://github.com/ChatArch/mychat-cli/actions/workflows/ci.yml" in readme_text
    assert "actions/workflows/ci.yml/badge.svg" in readme_text
    assert "https://arch.gh.wzhecnu.cn/mychat-cli/" in readme_text
    assert "OWNER/REPO" not in readme_text
    assert "docs-mkdocs" in readme_text
    assert "[英文版](README.en.md)" in readme_text
    assert "[English](README.en.md)" not in readme_text
    assert "mychat_cli --help" in readme_text
    assert "mychat_cli --version" in readme_text
    assert "mychat_cli --tree" in readme_text
    assert "mychat_cli --tree-brief" in readme_text
    assert "按场景选择文档" in readme_text
    assert "docs/cli-tree.md" in readme_text
    assert "docs/capability-map.md" in readme_text
    assert "hello ChatArch" not in readme_text
    assert "CommandSchema" in readme_text
    config_text = (project_dir / "src" / "mychat_cli" / "config.py").read_text(
        encoding="utf-8"
    )
    assert "class MychatCliConfig(BaseEnvConfig):" in config_text
    assert '_aliases = ["mychat_cli"]' in config_text
    assert '_storage_dir = "MychatCli"' in config_text
    assert "def test(cls) -> None:" in config_text
    assert "Schema loaded; no network test is required." in config_text


def test_chatpypi_init_help_does_not_expose_cname_options():
    runner = CliRunner()

    result = runner.invoke(cli, ["init", "--help"])

    assert result.exit_code == 0
    assert "--docs-domain" in result.output
    assert "CNAME" not in result.output
    assert "with-docs-cname" not in result.output
    assert "without-docs-cname" not in result.output


def test_chatpypi_init_chatarch_template_accepts_custom_docs_domain(tmp_path):
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
            "--docs-domain",
            "docs.example.com",
        ],
    )

    assert result.exit_code == 0
    assert not (project_dir / "docs" / "CNAME").exists()
    assert 'Documentation = "https://docs.example.com/mychat-cli/"' in (
        project_dir / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert "https://docs.example.com/mychat-cli/" in (project_dir / "README.md").read_text(
        encoding="utf-8"
    )
    assert "site_url: https://docs.example.com/mychat-cli/" in (
        project_dir / "mkdocs.yml"
    ).read_text(encoding="utf-8")
    preview_text = (project_dir / ".github" / "workflows" / "preview.yaml").read_text(
        encoding="utf-8"
    )
    assert "Path(\"mkdocs.yml\")" in preview_text
    assert "CHATARCH_PREVIEW_URL" in preview_text
    assert "https://docs.example.com/${" + "repo}/dev/" not in preview_text


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
    assert '"chatstyle>=0.2.0,<0.3.0"' in pyproject_text
    assert '"chatenv>=0.2.11,<0.3.0"' in pyproject_text
    assert '[project.entry-points."chatenv.configs"]' in pyproject_text
    assert 'mychat_cli = "mychat_cli.config"' in pyproject_text
    assert 'docs = ["mkdocs' not in pyproject_text
    assert 'Homepage = "https://github.com/ChatArch/mychat-cli"' in pyproject_text
    assert 'Documentation = "https://arch.gh.wzhecnu.cn/mychat-cli/"' not in pyproject_text
    readme_text = (project_dir / "README.md").read_text(encoding="utf-8")
    assert "docs-mkdocs" not in readme_text
    assert "actions/workflows/ci.yml" not in readme_text
