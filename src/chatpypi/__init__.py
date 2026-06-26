"""ChatPyPI package lifecycle helpers.

ChatPyPI provides importable Python APIs for scaffolding, building, checking,
probing, and uploading Python package distributions. The ``chatpypi`` CLI is a
thin adapter over these APIs.
"""

from .main import (
    CommandResult,
    DoctorCheck,
    ProjectMetadata,
    PyPICommandError,
    RepositoryCheck,
    ScaffoldResult,
    build_package,
    check_distributions,
    check_repository_conflicts,
    normalize_module_name,
    read_project_metadata,
    resolve_dist_dir,
    scaffold_package,
    upload_distributions,
)

__all__ = [
    "__version__",
    "CommandResult",
    "DoctorCheck",
    "ProjectMetadata",
    "PyPICommandError",
    "RepositoryCheck",
    "ScaffoldResult",
    "build_package",
    "check_distributions",
    "check_repository_conflicts",
    "normalize_module_name",
    "read_project_metadata",
    "resolve_dist_dir",
    "scaffold_package",
    "upload_distributions",
]

__version__ = "0.2.1"
