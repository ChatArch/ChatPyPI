from pathlib import Path

import chatpypi
from chatpypi import __version__


def test_version_present():
    assert __version__ == "0.1.3"


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
