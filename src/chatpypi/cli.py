from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import click

from chatstyle import INTERACTIVE_OPTION_HELP
from chatstyle import (
    abort_if_force_without_tty,
    abort_if_missing_without_tty,
    ask_confirm,
    ask_select,
    ask_text,
    resolve_interactive_mode,
)

from chatpypi.main import (
    PyPICommandError,
    _ensure_empty_or_missing,
    build_package,
    check_distributions,
    check_repository_conflicts,
    read_project_metadata,
    resolve_dist_dir,
    scaffold_package,
    upload_distributions,
)


def _project_options(func):
    func = click.option(
        "--dist-dir",
        type=click.Path(path_type=Path, file_okay=False),
        default=None,
        help="Distribution directory. Defaults to <project-dir>/dist.",
    )(func)
    func = click.option(
        "--project-dir",
        type=click.Path(path_type=Path, file_okay=False),
        default=Path("."),
        show_default=True,
        help="Project directory containing pyproject.toml.",
    )(func)
    return func


def _echo_result_output(result) -> None:
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        click.echo(stdout)
    if stderr:
        click.echo(stderr, err=True)


def _print_files(files: list[Path], title: str) -> None:
    click.echo(title)
    for path in files:
        click.echo(f"- {path}")


def _raise_click_error(exc: Exception) -> None:
    raise click.ClickException(str(exc)) from exc


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _resolve_init_inputs(
    *,
    name: str | None,
    description: str | None,
    initial_version: str,
    requires_python: str,
    license_name: str,
    author: str | None,
    email: str | None,
    project_dir: Path | None,
    template: str = "default",
) -> tuple[str, str | None, str, str, str, str | None, str | None, Path]:
    package_name = _normalize_optional_text(name)
    if not package_name and project_dir is not None and project_dir.name:
        package_name = project_dir.name
    if not package_name:
        raise click.ClickException(
            "Package name is required. Pass NAME or --project-dir."
        )

    target_dir = (project_dir or Path(package_name)).resolve()
    return (
        package_name,
        _normalize_optional_text(description) or f"{package_name} package",
        initial_version or "0.1.0",
        requires_python or _default_requires_python(template),
        license_name or "MIT",
        _normalize_optional_text(author),
        _normalize_optional_text(email),
        target_dir,
    )


def _default_requires_python(template: str) -> str:
    if template == "chatarch":
        return ">=3.10"
    return ">=3.9"


def _option_was_default(name: str) -> bool:
    ctx = click.get_current_context(silent=True)
    if not ctx:
        return False
    try:
        return ctx.get_parameter_source(name) == click.core.ParameterSource.DEFAULT
    except Exception:
        return False


def _is_name_missing(name: str | None, project_dir: Path | None) -> bool:
    package_name = _normalize_optional_text(name)
    return not package_name and not (project_dir is not None and project_dir.name)


def _read_git_config(key: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", key],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _resolve_project_dir(project_dir: Path) -> Path:
    return project_dir.resolve()


def _resolve_project_and_dist_dirs(
    project_dir: Path, dist_dir: Path | None
) -> tuple[Path, Path]:
    resolved_project_dir = _resolve_project_dir(project_dir)
    resolved_dist_dir = resolve_dist_dir(
        resolved_project_dir,
        dist_dir.resolve() if dist_dir else None,
    )
    return resolved_project_dir, resolved_dist_dir


@click.group(name="chatpypi")
def cli():
    """Python package lifecycle and PyPI operations helpers."""
    pass


@cli.group(name="pkg")
def pkg():
    """Package scaffold/build/check/upload/probe helpers."""
    pass


@cli.group(name="auth")
def auth():
    """Authentication, session, and bootstrap helpers."""
    pass


@auth.group(name="session")
def auth_session():
    """Inspect and manage local PyPI session files."""
    pass


@cli.group(name="profile")
def profile():
    """Manage local ChatPyPI profiles."""
    pass


@cli.group(name="config")
def config():
    """Manage local ChatPyPI config."""
    pass


@cli.group(name="project")
def project():
    """Read current-account project views."""
    pass


@cli.group(name="publisher")
def publisher():
    """Read or manage current-account publisher views."""
    pass


@cli.group(name="token")
def token():
    """Read or manage PyPI API tokens."""
    pass


@cli.group(name="doctor")
def doctor():
    """Run local configuration and session checks."""
    pass


@cli.group(name="docs")
def docs():
    """Show documentation links and usage examples."""
    pass


def _resolve_secret_env_var(
    *,
    option_label: str,
    env_var_name: str | None,
) -> str | None:
    if not env_var_name:
        return None
    env_var = env_var_name.strip()
    if not env_var:
        return None
    value = os.environ.get(env_var)
    if value is None:
        raise click.ClickException(
            f"{option_label} references unset environment variable: {env_var}"
        )
    if not value:
        raise click.ClickException(
            f"{option_label} references empty environment variable: {env_var}"
        )
    return value


def _planned_command_notice(command_path: str, summary: str) -> None:
    click.echo(f"{command_path} is reserved for the new ChatPyPI infra.")
    click.echo(summary)
    click.echo("This command tree is being introduced before the full workflow lands.")


def _load_session_payload(session_file: Path) -> dict:
    try:
        return json.loads(session_file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise click.ClickException(f"Session file not found: {session_file}") from exc
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Session file is not valid JSON: {session_file}: {exc}"
        ) from exc


def _session_summary(payload: dict, session_file: Path) -> dict[str, object]:
    cookies = payload.get("cookies")
    csrf = payload.get("csrf")
    meta = payload.get("meta")
    return {
        "path": str(session_file),
        "provider": payload.get("provider") or "pypi",
        "username": payload.get("username"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
        "cookie_count": len(cookies) if isinstance(cookies, list) else 0,
        "has_last_seen_csrf": bool(
            isinstance(csrf, dict) and csrf.get("last_seen_token")
        ),
        "email_verified": (
            meta.get("email_verified") if isinstance(meta, dict) else None
        ),
        "two_factor_enabled": (
            meta.get("two_factor_enabled") if isinstance(meta, dict) else None
        ),
    }


def _echo_json(payload: dict[str, object]) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


@cli.command(name="init")
@click.argument("name", required=False)
@click.option(
    "-t",
    "--template",
    type=click.Choice(["default", "chatarch"]),
    default="default",
    show_default=True,
    help="Project scaffold template.",
)
@click.option("--email", default=None, help="Author email to record in pyproject.toml.")
@click.option("--author", default=None, help="Author name to record in pyproject.toml.")
@click.option(
    "--license",
    "license_name",
    default="MIT",
    show_default=True,
    help="Project license template: MIT, Apache-2.0, BSD-3-Clause, GPL-3.0-only, or Proprietary.",
)
@click.option(
    "--version",
    "initial_version",
    default="0.1.0",
    show_default=True,
    help="Initial package version written to src/<module>/__init__.py.",
)
@click.option(
    "--python",
    "requires_python",
    default=">=3.9",
    show_default=True,
    help="Supported Python version specifier.",
)
@click.option("--description", default=None, help="Project description.")
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Target directory to create. Defaults to ./{name}.",
)
@click.option(
    "--with-mkdocs/--without-mkdocs",
    "include_mkdocs",
    default=None,
    help="Create mkdocs files for chatarch template. Defaults to on for chatarch.",
)
@click.option(
    "--with-workflows/--without-workflows",
    "include_workflows",
    default=None,
    help="Create GitHub workflow files for chatarch template. Defaults to on for chatarch.",
)
@click.option(
    "--with-chatenv-provider/--without-chatenv-provider",
    "include_chatenv_provider",
    default=False,
    show_default=True,
    help="Create ChatEnv provider config.py and chatenv.configs entry point for chatarch template.",
)
@click.option(
    "--chatenv-provider-name",
    default=None,
    help="Entry point name for --with-chatenv-provider. Defaults to the module name.",
)
@click.option(
    "--interactive/--no-interactive",
    "interactive",
    "-i/-I",
    default=None,
    help=INTERACTIVE_OPTION_HELP,
)
def init(
    name: str | None,
    template: str,
    description: str | None,
    initial_version: str,
    requires_python: str,
    license_name: str,
    author: str | None,
    email: str | None,
    project_dir: Path | None,
    include_mkdocs: bool | None,
    include_workflows: bool | None,
    include_chatenv_provider: bool,
    chatenv_provider_name: str | None,
    interactive: bool | None,
):
    """Scaffold a minimal src-layout Python package."""
    if _option_was_default("requires_python"):
        requires_python = _default_requires_python(template)

    missing_required = _is_name_missing(name, project_dir)
    usage = (
        "Usage: chatpypi init [NAME] [-t default|chatarch] [--project-dir PATH] "
        "[--description TEXT] [--version TEXT] [--python TEXT] [--license TEXT] "
        "[--author TEXT] [--email TEXT] [-i|-I]"
    )
    resolution = resolve_interactive_mode(
        interactive=interactive,
        auto_prompt_condition=missing_required,
    )
    interactive = resolution.interactive
    can_prompt = resolution.can_prompt
    force_interactive = resolution.force_interactive
    need_prompt = resolution.need_prompt
    abort_if_force_without_tty(force_interactive, can_prompt, usage)
    abort_if_missing_without_tty(
        missing_required=missing_required,
        interactive=interactive,
        can_prompt=can_prompt,
        message="Package name is required. Pass NAME or --project-dir.",
        usage=usage,
    )

    if need_prompt:
        template = ask_select(
            "选择模板",
            choices=[
                "default - minimal Python package",
                "chatarch - ChatArch CLI/docs/tests/automation scaffold",
            ],
        ).split(" - ", 1)[0]
        name_default = _normalize_optional_text(name) or (
            project_dir.name if project_dir is not None and project_dir.name else ""
        )
        name = ask_text("package_name", default=name_default)
        normalized_name = _normalize_optional_text(name)
        if not normalized_name:
            raise click.ClickException(
                "Package name is required. Pass NAME or --project-dir."
            )

        project_dir_default = str(project_dir or Path(normalized_name))
        project_dir = Path(
            ask_text("project_dir", default=project_dir_default)
        ).expanduser()
        try:
            _ensure_empty_or_missing(project_dir)
        except PyPICommandError as exc:
            _raise_click_error(exc)
        description = ask_text(
            "description",
            default=_normalize_optional_text(description)
            or f"{normalized_name} package",
        )
        initial_version = ask_text("version", default=initial_version or "0.1.0")
        if _option_was_default("requires_python"):
            requires_python = _default_requires_python(template)
        requires_python = ask_text("requires_python", default=requires_python)
        license_name = ask_text("license", default=license_name or "MIT")
        if include_mkdocs is None and template == "chatarch":
            include_mkdocs = ask_confirm(
                "Create mkdocs documentation files?",
                default=True,
            )
        elif include_mkdocs is None:
            include_mkdocs = False
        if include_workflows is None and template == "chatarch":
            include_workflows = ask_confirm(
                "Create GitHub workflow files?",
                default=True,
            )
        elif include_workflows is None:
            include_workflows = False
        author = ask_text(
            "author",
            default=_normalize_optional_text(author)
            or _read_git_config("user.name")
            or "",
        )
        email = ask_text(
            "email",
            default=_normalize_optional_text(email)
            or _read_git_config("user.email")
            or "",
        )

    (
        package_name,
        description,
        initial_version,
        requires_python,
        license_name,
        author,
        email,
        target_dir,
    ) = _resolve_init_inputs(
        name=name,
        description=description,
        initial_version=initial_version,
        requires_python=requires_python,
        license_name=license_name,
        author=author,
        email=email,
        project_dir=project_dir,
        template=template,
    )
    if chatenv_provider_name and not include_chatenv_provider:
        raise click.ClickException(
            "--chatenv-provider-name requires --with-chatenv-provider."
        )
    if include_chatenv_provider and template != "chatarch":
        raise click.ClickException(
            "--with-chatenv-provider is only supported by the chatarch template."
        )
    try:
        result = scaffold_package(
            package_name=package_name,
            project_dir=target_dir,
            initial_version=initial_version,
            description=description,
            requires_python=requires_python,
            license_name=license_name,
            author=author,
            email=email,
            template=template,
            include_mkdocs=include_mkdocs,
            include_workflows=include_workflows,
            include_chatenv_provider=include_chatenv_provider,
            chatenv_provider_name=chatenv_provider_name,
        )
    except PyPICommandError as exc:
        _raise_click_error(exc)

    click.echo(f"Created Python package scaffold: {result.package_name}")
    click.echo(f"project_dir={result.project_dir}")
    click.echo(f"module_name={result.module_name}")
    _print_files(result.created_files, "Created files:")


@cli.command(name="build")
@click.option("--wheel", is_flag=True, help="Build wheel only.")
@click.option("--sdist", is_flag=True, help="Build source distribution only.")
@click.option(
    "--clean/--no-clean",
    default=True,
    show_default=True,
    help="Clean old files in dist directory first.",
)
@_project_options
def build(
    project_dir: Path, dist_dir: Path | None, clean: bool, sdist: bool, wheel: bool
):
    """Build wheel and/or source distribution with python -m build."""
    project_dir, dist_dir = _resolve_project_and_dist_dirs(project_dir, dist_dir)
    click.echo(f"Building distributions from {project_dir} into {dist_dir}...")
    try:
        result, files = build_package(
            project_dir,
            dist_dir,
            clean=clean,
            sdist=sdist,
            wheel=wheel,
        )
    except PyPICommandError as exc:
        _raise_click_error(exc)
    _echo_result_output(result)
    _print_files(files, "Built distributions:")


@cli.command(name="check")
@click.option(
    "--strict", is_flag=True, help="Fail on warnings reported by twine check."
)
@_project_options
def check(project_dir: Path, dist_dir: Path | None, strict: bool):
    """Validate built distributions with twine check."""
    project_dir, dist_dir = _resolve_project_and_dist_dirs(project_dir, dist_dir)
    try:
        result, files = check_distributions(
            project_dir,
            dist_dir,
            strict=strict,
        )
    except PyPICommandError as exc:
        _raise_click_error(exc)
    _echo_result_output(result)
    _print_files(files, "Checked distributions:")


@cli.command(name="upload")
@click.option(
    "--skip-existing", is_flag=True, help="Pass --skip-existing to twine upload."
)
@click.option(
    "--repository-url",
    default=None,
    help="Custom repository upload URL. Overrides --repository.",
)
@click.option(
    "--repository",
    type=click.Choice(["testpypi", "pypi"]),
    default="pypi",
    show_default=True,
    help="Target repository for twine upload.",
)
@click.option(
    "--username",
    default=None,
    help="Explicit twine username. Use __token__ for API tokens.",
)
@click.option(
    "--password-env",
    default=None,
    help="Environment variable that stores the upload password.",
)
@click.option(
    "--token-env",
    default=None,
    help="Environment variable that stores a PyPI API token. Implies username=__token__.",
)
@_project_options
def upload(
    project_dir: Path,
    dist_dir: Path | None,
    skip_existing: bool,
    repository_url: str | None,
    repository: str,
    username: str | None,
    password_env: str | None,
    token_env: str | None,
):
    """Upload built distributions with the default twine upload behavior."""
    if password_env and token_env:
        raise click.ClickException(
            "--password-env and --token-env are mutually exclusive."
        )
    upload_env: dict[str, str] | None = None
    resolved_username = _normalize_optional_text(username)
    if token_env:
        resolved_username = "__token__"
        token_value = _resolve_secret_env_var(
            option_label="--token-env",
            env_var_name=token_env,
        )
        upload_env = dict(os.environ)
        upload_env["TWINE_PASSWORD"] = token_value
    elif password_env:
        password_value = _resolve_secret_env_var(
            option_label="--password-env",
            env_var_name=password_env,
        )
        upload_env = dict(os.environ)
        upload_env["TWINE_PASSWORD"] = password_value

    project_dir, dist_dir = _resolve_project_and_dist_dirs(project_dir, dist_dir)
    click.echo(f"Uploading distributions from {dist_dir} with `twine upload`...")
    try:
        result, files = upload_distributions(
            project_dir,
            dist_dir,
            skip_existing=skip_existing,
            repository=repository,
            repository_url=repository_url,
            username=resolved_username,
            env=upload_env,
        )
    except PyPICommandError as exc:
        _raise_click_error(exc)
    _echo_result_output(result)
    _print_files(files, "Uploaded distributions:")


@cli.command(name="probe")
@click.argument("package_name", required=False)
@click.option(
    "--repository-url",
    default=None,
    help="Custom repository URL. Overrides --repository.",
)
@click.option(
    "--repository",
    type=click.Choice(["testpypi", "pypi"]),
    default="pypi",
    show_default=True,
    help="Target repository for exact project/version releaseability checks.",
)
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("."),
    show_default=True,
    help="Project directory containing pyproject.toml for default metadata lookup.",
)
def probe(
    project_dir: Path,
    repository: str,
    repository_url: str | None,
    package_name: str | None,
):
    """Check whether an exact package name is available on PyPI."""
    project_dir = _resolve_project_dir(project_dir)
    try:
        metadata = read_project_metadata(project_dir)
    except PyPICommandError:
        metadata = None

    target_name = _normalize_optional_text(package_name) or (
        metadata.name if metadata else None
    )
    if not target_name:
        raise click.ClickException(
            "Package name is required. Pass NAME or provide a readable pyproject.toml."
        )

    try:
        repository_checks = check_repository_conflicts(
            target_name,
            repository=repository,
            repository_url=repository_url,
        )
    except PyPICommandError as exc:
        _raise_click_error(exc)

    for item in repository_checks:
        click.echo(f"[{item.status.upper()}] {item.label}: {item.detail}")
        if item.hint:
            click.echo(f"  hint: {item.hint}")
    if any(item.status == "fail" for item in repository_checks):
        raise click.ClickException("Repository conflict checks found blocking issues.")


@auth.command(name="login")
def auth_login():
    """Plan the future login workflow entry point."""
    _planned_command_notice(
        "chatpypi auth login",
        "Planned to exchange username/password/TOTP for a reusable local session file.",
    )


@auth.command(name="logout")
def auth_logout():
    """Plan the future logout workflow entry point."""
    _planned_command_notice(
        "chatpypi auth logout",
        "Planned to clear or invalidate the current local PyPI session.",
    )


@auth.command(name="whoami")
@click.option(
    "--session-file",
    type=click.Path(path_type=Path, dir_okay=False),
    envvar="PYPI_SESSION_FILE",
    default=None,
    help="Session file to inspect. Defaults to $PYPI_SESSION_FILE.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
def auth_whoami(session_file: Path | None, output_format: str):
    """Inspect the current local session summary."""
    if session_file is None:
        raise click.ClickException(
            "Session file is required. Pass --session-file or set PYPI_SESSION_FILE."
        )
    payload = _load_session_payload(session_file)
    summary = _session_summary(payload, session_file)
    if output_format == "json":
        _echo_json(summary)
        return
    click.echo(f"profile session: {summary['path']}")
    click.echo(f"provider={summary['provider']}")
    click.echo(f"username={summary['username'] or 'unknown'}")
    click.echo(f"updated_at={summary['updated_at'] or 'unknown'}")
    click.echo(
        "email_verified="
        + ("true" if summary["email_verified"] is True else "false" if summary["email_verified"] is False else "unknown")
    )
    click.echo(
        "two_factor_enabled="
        + ("true" if summary["two_factor_enabled"] is True else "false" if summary["two_factor_enabled"] is False else "unknown")
    )


@auth.command(name="register")
def auth_register():
    """Plan the future register workflow entry point."""
    _planned_command_notice(
        "chatpypi auth register",
        "Planned as an assist-first workflow. Full machine-only registration is not guaranteed.",
    )


@auth.command(name="verify-email")
def auth_verify_email():
    """Plan the future verify-email workflow entry point."""
    _planned_command_notice(
        "chatpypi auth verify-email",
        "Planned to consume a one-time verify-email link or token during bootstrap.",
    )


@auth.command(name="setup-2fa")
def auth_setup_2fa():
    """Plan the future setup-2fa workflow entry point."""
    _planned_command_notice(
        "chatpypi auth setup-2fa",
        "Planned to guide TOTP/WebAuthn setup and persist the private bootstrap artifacts locally.",
    )


@auth.command(name="recovery-codes")
def auth_recovery_codes():
    """Plan the future recovery-codes workflow entry point."""
    _planned_command_notice(
        "chatpypi auth recovery-codes",
        "Planned to summarize, regenerate, or store recovery codes with explicit user confirmation.",
    )


@auth_session.command(name="show")
@click.option(
    "--session-file",
    type=click.Path(path_type=Path, dir_okay=False),
    envvar="PYPI_SESSION_FILE",
    default=None,
    help="Session file to inspect. Defaults to $PYPI_SESSION_FILE.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format.",
)
def auth_session_show(session_file: Path | None, output_format: str):
    """Show a non-sensitive summary of the local session file."""
    if session_file is None:
        raise click.ClickException(
            "Session file is required. Pass --session-file or set PYPI_SESSION_FILE."
        )
    payload = _load_session_payload(session_file)
    summary = _session_summary(payload, session_file)
    if output_format == "json":
        _echo_json(summary)
        return
    click.echo(f"session_file={summary['path']}")
    click.echo(f"provider={summary['provider']}")
    click.echo(f"username={summary['username'] or 'unknown'}")
    click.echo(f"created_at={summary['created_at'] or 'unknown'}")
    click.echo(f"updated_at={summary['updated_at'] or 'unknown'}")
    click.echo(f"cookie_count={summary['cookie_count']}")
    click.echo(
        "has_last_seen_csrf="
        + ("true" if summary["has_last_seen_csrf"] else "false")
    )


@auth_session.command(name="export")
def auth_session_export():
    """Plan the future session export workflow entry point."""
    _planned_command_notice(
        "chatpypi auth session export",
        "Planned to export an in-memory or browser-derived session to the local session file.",
    )


@auth_session.command(name="import")
def auth_session_import():
    """Plan the future session import workflow entry point."""
    _planned_command_notice(
        "chatpypi auth session import",
        "Planned to restore a saved local session into the active ChatPyPI runtime.",
    )


@auth_session.command(name="clear")
@click.option(
    "--session-file",
    type=click.Path(path_type=Path, dir_okay=False),
    envvar="PYPI_SESSION_FILE",
    default=None,
    help="Session file to remove. Defaults to $PYPI_SESSION_FILE.",
)
def auth_session_clear(session_file: Path | None):
    """Delete the local session file if it exists."""
    if session_file is None:
        raise click.ClickException(
            "Session file is required. Pass --session-file or set PYPI_SESSION_FILE."
        )
    if session_file.exists():
        session_file.unlink()
        click.echo(f"Removed session file: {session_file}")
    else:
        click.echo(f"Session file already absent: {session_file}")


def _planned_group_leaf(group, name: str, summary: str):
    @group.command(name=name)
    def _command():
        _planned_command_notice(f"chatpypi {group.name} {name}", summary)

    return _command


_planned_group_leaf(profile, "list", "Planned to list local named ChatPyPI profiles.")
_planned_group_leaf(profile, "show", "Planned to show the non-sensitive fields of a local profile.")
_planned_group_leaf(profile, "use", "Planned to switch the active local profile.")
_planned_group_leaf(profile, "create", "Planned to create a local profile for PyPI work.")
_planned_group_leaf(profile, "delete", "Planned to delete a local profile with confirmation.")
_planned_group_leaf(config, "list", "Planned to list persisted ChatPyPI config keys and values.")
_planned_group_leaf(config, "get", "Planned to read one persisted ChatPyPI config key.")
_planned_group_leaf(config, "set", "Planned to write one persisted ChatPyPI config key.")
_planned_group_leaf(config, "unset", "Planned to remove one persisted ChatPyPI config key.")
_planned_group_leaf(project, "list", "Planned to list the logged-in account's PyPI projects.")
_planned_group_leaf(project, "show", "Planned to show one logged-in account PyPI project.")
_planned_group_leaf(publisher, "list", "Planned to list the logged-in account's active publishers.")
_planned_group_leaf(
    publisher,
    "pending-list",
    "Planned to list pending publishers from the logged-in account publishing page.",
)
_planned_group_leaf(
    publisher,
    "pending-add",
    "Planned as a checkpoint-aware browser-assisted publisher creation flow.",
)
_planned_group_leaf(
    publisher,
    "pending-remove",
    "Planned as a checkpoint-aware browser-assisted publisher removal flow.",
)
_planned_group_leaf(token, "list", "Planned to list token summaries without revealing token values.")
_planned_group_leaf(
    token,
    "create",
    "Planned to create a PyPI API token and persist the one-time secret in a private store.",
)
_planned_group_leaf(token, "revoke", "Planned to revoke a PyPI API token with confirmation.")
_planned_group_leaf(
    doctor,
    "check",
    "Planned to validate the active profile, session file, and read-only PyPI connectivity.",
)


@docs.command(name="links")
def docs_links():
    """Show the most relevant documentation entry points."""
    click.echo("ChatPyPI docs: https://ChatArch.github.io/ChatPyPI")
    click.echo("PyPI user docs: https://docs.pypi.org/")
    click.echo("Trusted publishing guide: https://docs.pypi.org/trusted-publishers/")


@docs.command(name="examples")
def docs_examples():
    """Show common CLI examples for the current infra direction."""
    click.echo("chatpypi pkg init chatpypi-demo --project-dir ./chatpypi-demo")
    click.echo("chatpypi pkg build --project-dir ./chatpypi-demo")
    click.echo("chatpypi pkg check --project-dir ./chatpypi-demo")
    click.echo(
        "chatpypi pkg upload --project-dir ./chatpypi-demo --token-env PYPI_API_TOKEN"
    )
    click.echo("chatpypi auth session show")


@docs.command(name="open")
@click.argument("topic", required=False)
def docs_open(topic: str | None):
    """Print a documentation URL for a known topic."""
    routes = {
        None: "https://ChatArch.github.io/ChatPyPI",
        "pypi": "https://docs.pypi.org/",
        "trusted-publishing": "https://docs.pypi.org/trusted-publishers/",
        "api-tokens": "https://docs.pypi.org/api/tokens/",
    }
    target = routes.get(_normalize_optional_text(topic), routes[None])
    click.echo(target)


pkg.add_command(init)
pkg.add_command(build)
pkg.add_command(check)
pkg.add_command(upload)
pkg.add_command(probe)


KNOWN_COMMANDS = {
    "auth",
    "profile",
    "config",
    "pkg",
    "project",
    "publisher",
    "token",
    "doctor",
    "docs",
    "init",
    "build",
    "check",
    "upload",
    "probe",
    "--help",
    "-h",
}


def main() -> None:
    """Console-script entry point with chatpypi shortcut routing."""

    args = sys.argv[1:]
    if args:
        first = args[0]
        if first not in KNOWN_COMMANDS and not first.startswith("-"):
            args = ["init", *args]
    cli.main(args=args, prog_name="chatpypi")


if __name__ == "__main__":
    main()
