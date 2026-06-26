from pathlib import Path
import logging

import chatpypi
from chatpypi import CommandResult
from chatpypi import __version__
from chatpypi.config import (
    PyPIConfig,
    save_active_pypi_env_value,
    save_pypi_env_profile_value,
)


def test_version_present():
    assert __version__ == "0.2.3"


def test_public_package_api_exports_core_helpers(tmp_path):
    assert chatpypi.normalize_module_name("ChatPyPI") == "chatpypi"
    assert chatpypi.resolve_dist_dir(tmp_path) == tmp_path / "dist"
    assert issubclass(chatpypi.PyPICommandError, RuntimeError)
    assert callable(chatpypi.scaffold_package)
    assert callable(chatpypi.build_package)
    assert callable(chatpypi.check_distributions)
    assert callable(chatpypi.upload_distributions)
    assert callable(chatpypi.check_repository_conflicts)


def test_scaffold_package_importable_api_creates_project(tmp_path):
    project_dir = tmp_path / "DemoPkg"

    result = chatpypi.scaffold_package(
        package_name="DemoPkg",
        description="Demo package",
        initial_version="0.1.0",
        requires_python=">=3.10",
        license_name="MIT",
        author="ChatArch",
        email="1073853456@qq.com",
        project_dir=project_dir,
        template="default",
    )

    assert result.project_dir == project_dir
    assert result.package_name == "DemoPkg"
    assert result.module_name == "demopkg"
    assert (project_dir / "pyproject.toml").exists()
    assert (project_dir / "src" / "demopkg" / "__init__.py").exists()


def test_runtime_dependencies_include_build_and_twine():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert '"build>=1.2.0,<2.0.0"' in text
    assert '"twine>=6.0.0,<7.0.0"' in text
    assert '"requests>=2.31.0,<3.0.0"' in text


def test_chatenv_provider_entry_point_declared():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert '[project.entry-points."chatenv.configs"]' in text
    assert 'pypi = "chatpypi.config"' in text


def test_chatenv_pypi_config_schema():
    assert PyPIConfig._title == "PyPI Configuration"
    assert PyPIConfig._aliases == ["pypi", "chatpypi"]
    assert PyPIConfig._storage_dir == "PyPI"
    fields = PyPIConfig.get_fields()

    assert "PYPI_SESSION_TOKEN" in fields
    assert fields["PYPI_SESSION_TOKEN"].is_sensitive is True
    assert "PYPI_SESSION_FILE" not in fields
    assert fields["PYPI_API_TOKEN"].is_sensitive is True
    assert fields["PYPI_PASSWORD"].is_sensitive is True
    assert fields["PYPI_TOTP_SECRET"].is_sensitive is True


def test_session_token_save_does_not_backfill_process_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYPI_PASSWORD", "process-password-must-not-persist")
    monkeypatch.setenv("PYPI_API_TOKEN", "process-token-must-not-persist")
    monkeypatch.setenv("PYPI_TOTP_SECRET", "process-totp-must-not-persist")

    active_path = save_active_pypi_env_value("PYPI_SESSION_TOKEN", "encoded-session")
    profile_path = save_pypi_env_profile_value("RexWzh", "PYPI_SESSION_TOKEN", "encoded-profile-session")

    active_text = active_path.read_text(encoding="utf-8")
    profile_text = profile_path.read_text(encoding="utf-8")
    assert "PYPI_SESSION_TOKEN" in active_text
    assert "PYPI_SESSION_TOKEN" in profile_text
    assert "process-password-must-not-persist" not in active_text + profile_text
    assert "process-token-must-not-persist" not in active_text + profile_text
    assert "process-totp-must-not-persist" not in active_text + profile_text


def test_chatenv_pypi_config_test_is_side_effect_free(capsys):
    PyPIConfig.test()

    output = capsys.readouterr().out
    assert "Testing PyPI Configuration" in output
    assert "Schema loaded" in output


def test_build_package_logs_and_returns_artifacts(tmp_path, caplog):
    project_dir = tmp_path / "DemoBuild"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    def fake_runner(args, cwd):
        dist_dir = Path(args[args.index("--outdir") + 1])
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "demo-0.1.0-py3-none-any.whl").write_text(
            "wheel", encoding="utf-8"
        )
        return CommandResult(args=list(args), returncode=0, stdout="built", stderr="")

    with caplog.at_level(logging.INFO, logger="chatpypi.main"):
        result, files = chatpypi.build_package(project_dir, runner=fake_runner)

    assert result.returncode == 0
    assert [path.name for path in files] == ["demo-0.1.0-py3-none-any.whl"]
    assert "Building package distributions" in caplog.text
    assert "Built package distributions" in caplog.text


def test_upload_distributions_accepts_two_argument_runner(tmp_path):
    project_dir = tmp_path / "DemoUpload"
    dist_dir = project_dir / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "demo-0.1.0-py3-none-any.whl").write_text(
        "wheel", encoding="utf-8"
    )

    def old_style_runner(args, cwd):
        assert "upload" in args
        assert cwd == project_dir
        return CommandResult(args=list(args), returncode=0, stdout="uploaded", stderr="")

    result, files = chatpypi.upload_distributions(
        project_dir,
        runner=old_style_runner,
    )

    assert result.returncode == 0
    assert result.stdout == "uploaded"
    assert [path.name for path in files] == ["demo-0.1.0-py3-none-any.whl"]


def test_check_distributions_error_mentions_chatpypi_build(tmp_path):
    project_dir = tmp_path / "EmptyDist"
    project_dir.mkdir()

    try:
        chatpypi.check_distributions(project_dir)
    except chatpypi.PyPICommandError as exc:
        assert "Run `chatpypi build` first" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected PyPICommandError")
