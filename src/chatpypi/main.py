from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
import json
import importlib.util
import logging
from pathlib import Path
import re
import subprocess
import sys
import textwrap
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


DEFAULT_DIST_DIRNAME = "dist"
DEFAULT_CHATARCH_DOCS_DOMAIN = "arch.gh.wzhecnu.cn"
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

LICENSE_TEMPLATES = {
    "MIT": """MIT License

Copyright (c) {year} {author}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
""",
    "Apache-2.0": """Apache License
Version 2.0, January 2004
https://www.apache.org/licenses/

Copyright {year} {author}

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
""",
    "BSD-3-Clause": """BSD 3-Clause License

Copyright (c) {year}, {author}
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE.
""",
    "GPL-3.0-only": """GNU GENERAL PUBLIC LICENSE
Version 3, 29 June 2007

Copyright (c) {year} {author}

This project is licensed under the GNU General Public License version 3.
See https://www.gnu.org/licenses/gpl-3.0.en.html for the full license text.
""",
    "Proprietary": """Proprietary License

Copyright (c) {year} {author}. All rights reserved.

This software is proprietary and confidential. Unauthorized copying,
distribution, modification, or use of this software is prohibited without
prior written permission.
""",
}


class PyPICommandError(RuntimeError):
    """Raised when a package operation cannot be completed safely."""


@dataclass
class ProjectMetadata:
    name: str | None
    version: str | None
    version_source: str | None
    readme: str | None
    requires_python: str | None
    license_text: str | None
    dynamic_fields: list[str]


@dataclass
class DoctorCheck:
    label: str
    status: str
    detail: str
    hint: str | None = None


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class ScaffoldResult:
    project_dir: Path
    package_name: str
    module_name: str
    created_files: list[Path]


@dataclass
class RepositoryCheck:
    label: str
    status: str
    detail: str
    hint: str | None = None


def _extract_project_snippets(payload: dict | None) -> list[RepositoryCheck]:
    if not isinstance(payload, dict):
        return []
    info = payload.get("info")
    if not isinstance(info, dict):
        return []

    snippets: list[RepositoryCheck] = []
    version = info.get("version")
    if isinstance(version, str) and version.strip():
        snippets.append(RepositoryCheck("latest version", "info", version.strip()))

    release_entries = payload.get("urls")
    if not isinstance(release_entries, list):
        releases = payload.get("releases")
        if isinstance(releases, dict) and isinstance(version, str) and version.strip():
            release_entries = releases.get(version.strip())

    timestamps: list[tuple[datetime, str]] = []
    for release_item in release_entries if isinstance(release_entries, list) else []:
        if not isinstance(release_item, dict):
            continue
        uploaded = release_item.get("upload_time_iso_8601") or release_item.get(
            "upload_time"
        )
        if not isinstance(uploaded, str) or not uploaded.strip():
            continue
        normalized = uploaded.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        timestamps.append((parsed, uploaded.strip()))
    if timestamps:
        _, latest_uploaded = max(timestamps, key=lambda item: item[0])
        snippets.append(RepositoryCheck("latest release date", "info", latest_uploaded))

    summary = info.get("summary")
    if isinstance(summary, str) and summary.strip():
        snippets.append(RepositoryCheck("summary", "info", summary.strip()))

    author = info.get("author")
    if isinstance(author, str) and author.strip():
        snippets.append(RepositoryCheck("author", "info", author.strip()))

    author_email = info.get("author_email")
    if isinstance(author_email, str) and author_email.strip():
        snippets.append(RepositoryCheck("author email", "info", author_email.strip()))

    requires_python = info.get("requires_python")
    if isinstance(requires_python, str) and requires_python.strip():
        snippets.append(
            RepositoryCheck("requires python", "info", requires_python.strip())
        )

    project_url = info.get("project_url") or info.get("home_page")
    if isinstance(project_url, str) and project_url.strip():
        snippets.append(RepositoryCheck("project url", "info", project_url.strip()))

    return snippets


def _normalized_project_name(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def resolve_dist_dir(project_dir: Path, dist_dir: Path | None = None) -> Path:
    if dist_dir is None:
        return project_dir / DEFAULT_DIST_DIRNAME
    return dist_dir


def normalize_module_name(package_name: str) -> str:
    normalized = package_name.strip().replace("-", "_").replace(" ", "_")
    parts = [char if (char.isalnum() or char == "_") else "_" for char in normalized]
    module_name = "".join(parts).strip("_").lower()
    while "__" in module_name:
        module_name = module_name.replace("__", "_")
    if not module_name:
        raise PyPICommandError(
            "Package name must contain at least one valid letter or digit."
        )
    if module_name[0].isdigit():
        raise PyPICommandError("Module name cannot start with a digit.")
    return module_name


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _py_string_literal(value: str) -> str:
    return json.dumps(value)


def _pascal_identifier(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    if not parts:
        return "Config"
    return "".join(part[:1].upper() + part[1:].lower() for part in parts)


def _workflow_python_version(requires_python: str) -> str:
    match = re.search(r">=\s*(\d+\.\d+)", requires_python)
    if match:
        return match.group(1)
    return "3.10"


def _license_template_content(license_name: str, author: str | None) -> str:
    from datetime import date

    normalized = license_name.strip() or "MIT"
    template = LICENSE_TEMPLATES.get(normalized)
    if template is None:
        template = LICENSE_TEMPLATES["Proprietary"]
        if normalized.lower() not in {"proprietary", "unlicensed"}:
            return f"{normalized}\n\nCopyright (c) {date.today().year} {author or 'PROJECT OWNER'}.\n"
    return template.format(year=date.today().year, author=author or "PROJECT OWNER")


def _ensure_empty_or_missing(project_dir: Path) -> None:
    if not project_dir.exists():
        return
    if not project_dir.is_dir():
        raise PyPICommandError(
            f"Target path exists and is not a directory: {project_dir}"
        )
    if any(project_dir.iterdir()):
        raise PyPICommandError(f"Target directory is not empty: {project_dir}")


def _build_pyproject_content(
    package_name: str,
    module_name: str,
    description: str,
    requires_python: str,
    license_name: str,
    author: str | None,
    email: str | None,
) -> str:
    lines = [
        "[build-system]",
        'requires = ["setuptools>=61.0", "wheel"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[project]",
        f'name = "{_toml_escape(package_name)}"',
        'dynamic = ["version"]',
        f'description = "{_toml_escape(description)}"',
        'readme = "README.md"',
        f'requires-python = "{_toml_escape(requires_python)}"',
        f'license = "{_toml_escape(license_name)}"',
    ]
    if author and email:
        lines.append(
            f'authors = [{{name = "{_toml_escape(author)}", email = "{_toml_escape(email)}"}}]'
        )
    elif author:
        lines.append(f'authors = [{{name = "{_toml_escape(author)}"}}]')
    elif email:
        lines.append(f'authors = [{{email = "{_toml_escape(email)}"}}]')
    lines.extend(
        [
            f'keywords = ["{_toml_escape(module_name)}"]',
            "classifiers = [",
            '    "Programming Language :: Python :: 3",',
            '    "Operating System :: OS Independent",',
            "]",
            "",
            "[tool.setuptools.dynamic]",
            f'version = {{attr = "{module_name}.__version__"}}',
            "",
            "[tool.setuptools.packages.find]",
            'where = ["src"]',
            "",
            "[tool.setuptools]",
            "include-package-data = true",
            "",
        ]
    )
    return "\n".join(lines)


def _build_chatarch_pyproject_content(
    package_name: str,
    module_name: str,
    description: str,
    requires_python: str,
    license_name: str,
    author: str | None,
    email: str | None,
    include_mkdocs: bool = True,
    chatenv_provider_name: str | None = None,
    docs_domain: str | None = None,
) -> str:
    repo_slug = _chatarch_repo_slug(package_name)
    docs_url = _chatarch_docs_url(package_name, docs_domain)
    lines = [
        "[build-system]",
        'requires = ["setuptools>=61.0", "wheel"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[project]",
        f'name = "{_toml_escape(package_name)}"',
        'dynamic = ["version"]',
        f'description = "{_toml_escape(description)}"',
        'readme = "README.md"',
        f'requires-python = "{_toml_escape(requires_python)}"',
        f'license = "{_toml_escape(license_name)}"',
        'dependencies = ["click>=8.0", "chatstyle>=0.2.0,<0.3.0", "chatenv>=0.2.9,<0.3.0"]',
    ]
    if author and email:
        lines.append(
            f'authors = [{{name = "{_toml_escape(author)}", email = "{_toml_escape(email)}"}}]'
        )
    elif author:
        lines.append(f'authors = [{{name = "{_toml_escape(author)}"}}]')
    elif email:
        lines.append(f'authors = [{{email = "{_toml_escape(email)}"}}]')
    lines.extend(
        [
            f'keywords = ["{_toml_escape(module_name)}", "chatarch", "cli"]',
            "classifiers = [",
            '    "Programming Language :: Python :: 3",',
            '    "Operating System :: OS Independent",',
            "]",
            "",
            "[project.urls]",
            f'Homepage = "https://github.com/{_toml_escape(repo_slug)}"',
            f'Repository = "https://github.com/{_toml_escape(repo_slug)}"',
        ]
    )
    if include_mkdocs:
        lines.append(f'Documentation = "{_toml_escape(docs_url)}"')
    lines.extend(
        [
            "",
            "[project.scripts]",
            f'{module_name} = "{module_name}.cli:main"',
        ]
    )
    if chatenv_provider_name:
        lines.extend(
            [
                "",
                '[project.entry-points."chatenv.configs"]',
                f'{chatenv_provider_name} = "{module_name}.config"',
            ]
        )
    lines.extend(
        [
            "",
            "[project.optional-dependencies]",
            'dev = ["build", "pytest", "twine"]',
        ]
    )
    if include_mkdocs:
        lines.append(
            'docs = ["mkdocs>=1.6,<2.0", "mkdocs-material>=9.5,<9.7", '
            '"mkdocs-static-i18n>=1.2,<2.0", "mike>=2.0,<3.0"]'
        )
    lines.extend(
        [
            "",
            "[tool.setuptools.dynamic]",
            f'version = {{attr = "{module_name}.__version__"}}',
            "",
            "[tool.setuptools.packages.find]",
            'where = ["src"]',
            "",
            "[tool.setuptools]",
            "include-package-data = true",
            "",
        ]
    )
    return "\n".join(lines)


def _build_chatarch_chatenv_config_py(
    package_name: str,
    module_name: str,
    provider_name: str,
) -> str:
    class_name = f"{_pascal_identifier(module_name)}Config"
    storage_dir = _pascal_identifier(provider_name)
    env_key_prefix = module_name.upper()
    aliases = [provider_name]
    if module_name not in aliases:
        aliases.append(module_name)
    aliases_text = ", ".join(_py_string_literal(alias) for alias in aliases)
    env_key = f"{env_key_prefix}_API_KEY"
    return (
        textwrap.dedent(
            f'''\
            {_py_string_literal(f"Typed environment configuration for {package_name}.")}

            from chatenv import BaseEnvConfig, EnvField


            class {class_name}(BaseEnvConfig):
                {_py_string_literal(f"{package_name} ChatEnv configuration.")}

                _title = {_py_string_literal(f"{package_name} Configuration")}
                _aliases = [{aliases_text}]
                _storage_dir = {_py_string_literal(storage_dir)}

                @classmethod
                def test(cls) -> None:
                    """Validate schema registration without external side effects."""

                    print(f"Testing {{cls._title}}...")
                    print("Schema loaded; no network test is required.")

                {env_key_prefix}_API_KEY = EnvField(
                    {_py_string_literal(env_key)},
                    desc="API key",
                    is_sensitive=True,
                )


            __all__ = ["{class_name}"]
            '''
        ).strip()
        + "\n"
    )


def _chatarch_repo_slug(package_name: str) -> str:
    return f"ChatArch/{package_name}"


def _normalize_docs_domain(docs_domain: str | None) -> str:
    value = (docs_domain or DEFAULT_CHATARCH_DOCS_DOMAIN).strip().rstrip("/")
    if not value:
        return DEFAULT_CHATARCH_DOCS_DOMAIN
    if "://" in value:
        parsed = urllib_parse.urlparse(value)
        value = parsed.netloc or parsed.path
    value = value.strip().strip("/")
    if "/" in value:
        raise PyPICommandError("docs_domain must be a domain name, not a URL path.")
    return value


def _chatarch_docs_url(package_name: str, docs_domain: str | None = None) -> str:
    domain = _normalize_docs_domain(docs_domain)
    return f"https://{domain}/{package_name}/"


def _chatarch_badge_block(
    package_name: str,
    *,
    include_mkdocs: bool,
    include_workflows: bool,
    docs_domain: str | None = None,
) -> str:
    repo_slug = _chatarch_repo_slug(package_name)
    docs_url = _chatarch_docs_url(package_name, docs_domain)
    lines = [
        '<div align="center">',
        f'    <a href="https://pypi.python.org/pypi/{package_name}">',
        f'        <img src="https://img.shields.io/pypi/v/{package_name}.svg" alt="PyPI version" />',
        "    </a>",
    ]
    if include_workflows:
        lines.extend(
            [
                f'    <a href="https://github.com/{repo_slug}/actions/workflows/ci.yml">',
                f'        <img src="https://github.com/{repo_slug}/actions/workflows/ci.yml/badge.svg" alt="Tests" />',
                "    </a>",
            ]
        )
    if include_mkdocs:
        lines.extend(
            [
                f'    <a href="{docs_url}">',
                '        <img src="https://img.shields.io/badge/docs-mkdocs-blue.svg" alt="Documentation" />',
                "    </a>",
            ]
        )
    lines.append("</div>")
    return "\n".join(lines)


def _chatarch_layout_lines(*, include_mkdocs: bool) -> str:
    lines = [
        "- `src/`：包源码",
        "- `tests/code-tests/`：代码测试和历史测试迁移",
        "- `tests/cli-tests/`：真实 CLI 测试，doc-first",
        "- `tests/mock-cli-tests/`：mock/fake CLI 测试，doc-first",
    ]
    if include_mkdocs:
        lines.append("- `docs/`：长期维护文档，由 mkdocs 构建")
    return "\n".join(lines)


def _chatarch_layout_lines_en(*, include_mkdocs: bool) -> str:
    lines = [
        "- `src/`: package source code",
        "- `tests/code-tests/`: code tests and migrated historical tests",
        "- `tests/cli-tests/`: real CLI tests, doc-first",
        "- `tests/mock-cli-tests/`: mock/fake CLI tests, doc-first",
    ]
    if include_mkdocs:
        lines.append("- `docs/`: long-lived project docs built by mkdocs")
    return "\n".join(lines)


def _build_chatarch_readme(
    package_name: str,
    module_name: str,
    description: str,
    *,
    include_mkdocs: bool = True,
    include_workflows: bool = True,
    docs_domain: str | None = None,
) -> str:
    badges = _chatarch_badge_block(
        package_name,
        include_mkdocs=include_mkdocs,
        include_workflows=include_workflows,
        docs_domain=docs_domain,
    )
    layout = _chatarch_layout_lines(include_mkdocs=include_mkdocs)
    docs_url = _chatarch_docs_url(package_name, docs_domain)
    docs_section = ""
    if include_mkdocs:
        docs_section = f"""
文档入口：<{docs_url}>

按场景选择文档：

| 场景 | 文档 |
| --- | --- |
| 第一次安装、运行命令行、确认包可用 | [CLI 树](docs/cli-tree.md) |
| 校对当前包有哪些一等能力和边界 | [能力地图](docs/capability-map.md) |
| 从 Python 代码调用包能力 | [接口树](docs/interface-tree.md) |

"""
    return f"""\
{badges}

<div align="center">

[英文版](README.en.md) | [简体中文](README.md)
</div>

# {package_name}

{description}

{docs_section}## 快速开始

```bash
pip install -e \".[dev]"
{module_name} --help
{module_name} --version
{module_name} --tree
{module_name} --tree-brief
python -m pytest -q
python -m build
```

## 命令行规范

这个模板默认依赖 `chatstyle>=0.2.0,<0.3.0` 和 `chatenv>=0.2.9,<0.3.0`，新增命令应优先使用：

- `add_tree_option()` 提供共享的 `--tree` / `--tree-brief`，`render_click_tree()` 从已注册 Click 元数据生成命令树。
- `CommandSchema` / `CommandField` 描述输入。
- `add_interactive_option()` 提供统一 `-i/-I`。
- `resolve_command_inputs()` 统一缺参补问、默认值、TTY 与校验。
- 默认生成 `config.py` 和 `chatenv.configs` 入口点，使包可被 ChatEnv 发现；只有明确不需要 ChatEnv 接入时才使用 `--without-chatenv-provider`。

## 目录结构

{layout}

## 开发说明

扩展脚手架前，先阅读 `DEVELOP.md` 和 `AGENTS.md`。
"""


def _build_chatarch_readme_en(
    package_name: str,
    module_name: str,
    description: str,
    *,
    include_mkdocs: bool = True,
    include_workflows: bool = True,
    docs_domain: str | None = None,
) -> str:
    badges = _chatarch_badge_block(
        package_name,
        include_mkdocs=include_mkdocs,
        include_workflows=include_workflows,
        docs_domain=docs_domain,
    )
    layout = _chatarch_layout_lines_en(include_mkdocs=include_mkdocs)
    docs_url = _chatarch_docs_url(package_name, docs_domain)
    docs_section = ""
    if include_mkdocs:
        docs_section = f"""
Documentation entry: <{docs_url}en/>

Choose documentation by scenario:

| Scenario | Document |
| --- | --- |
| Install the package, run the CLI, and confirm it works | `docs/cli-tree.en.md` |
| Check first-class capabilities and current boundaries | `docs/capability-map.en.md` |
| Call package behavior directly from Python | `docs/interface-tree.md` |

"""
    return f"""\
{badges}

<div align="center">

[English](README.en.md) | [简体中文](README.md)
</div>

# {package_name}

{description}

{docs_section}## Quick Start

```bash
pip install -e \".[dev]"
{module_name} --help
{module_name} --version
{module_name} --tree
{module_name} --tree-brief
python -m pytest -q
python -m build
```

## CLI Contract

This template depends on `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.9,<0.3.0`. New commands should prefer:

- `add_tree_option()` for shared `--tree` / `--tree-brief` flags and `render_click_tree()` to render registered Click metadata.
- `CommandSchema` / `CommandField` for inputs.
- `add_interactive_option()` for the shared `-i/-I` switch.
- `resolve_command_inputs()` for missing args, defaults, TTY behavior, and validation.
- Generate `config.py` and a `chatenv.configs` entry point by default so the package is ChatEnv-discoverable; use `--without-chatenv-provider` only when ChatEnv integration is intentionally not needed.

## Layout

{layout}

## Development Notes

See `DEVELOP.md` and `AGENTS.md` before expanding the scaffold.
"""


def _build_chatarch_develop_md() -> str:
    return (
        textwrap.dedent(
            """
            # Development Guide

            ## CLI Rules

            - Use `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.9,<0.3.0` as the canonical CLI interaction runtime.
            - Use `add_tree_option()` for shared `--tree` / `--tree-brief` flags and `render_click_tree()` for programmatic Click-tree readback.
            - Prefer `CommandSchema`, `CommandField`, `add_interactive_option()`, and `resolve_command_inputs()` for new commands.
            - Missing required args should auto-enter interactive mode when recoverable.
            - `-i` forces interactive mode; `-I` disables prompting and must fail fast.
            - Prompt defaults must match actual execution defaults.
            - Sensitive values must stay masked in prompts and summaries.
            - Prefer lazy imports in CLI wiring and keep implementation imports local when possible.

            ## Docs and Tests

            - Use doc-first CLI testing.
            - Put real CLI coverage under `tests/cli-tests/`.
            - Put mock/fake CLI coverage under `tests/mock-cli-tests/`.
            - Keep `README.md`, `docs/`, and `CHANGELOG.md` in sync with user-facing changes.

            ## Automation

            - Keep automation small and reviewable.
            - Prefer commands that can run in CI without interactive prompts.
            - Ensure generated defaults are safe for local development.
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_changelog() -> str:
    return "# Changelog\n\n## YYYY-MM-DD\n\n### Added\n\n### Changed\n\n### Fixed\n"


def _build_chatarch_cli_py(module_name: str) -> str:
    return (
        textwrap.dedent(
            f"""
            \"\"\"CLI entrypoint for {module_name}.\"\"\"

            from __future__ import annotations

            import click
            from chatstyle import add_tree_option

            from {module_name} import __version__


            @click.group(name="{module_name}", invoke_without_command=True, no_args_is_help=True)
            @click.version_option(__version__, prog_name="{module_name}")
            @add_tree_option(renderer_options={{"root_name": "{module_name}"}})
            def main() -> None:
                \"\"\"{module_name} command line interface.\"\"\"
                # Add package-specific commands here. Prefer ChatStyle helpers for
                # interactive input when a command needs recoverable user input.
                pass


            if __name__ == "__main__":
                main()
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_test_cli_py(module_name: str) -> str:
    return (
        textwrap.dedent(
            f"""
            from click.testing import CliRunner

            from {module_name} import __version__
            from {module_name}.cli import main


            def test_version_option_reports_package_version():
                result = CliRunner().invoke(main, ["--version"])

                assert result.exit_code == 0
                assert f"{module_name}, version {{__version__}}" in result.output


            def test_help_lists_shared_tree_options():
                result = CliRunner().invoke(main, ["--help"])

                assert result.exit_code == 0
                assert "--tree" in result.output
                assert "--tree-brief" in result.output


            def test_tree_option_prints_registered_cli_tree():
                result = CliRunner().invoke(main, ["--tree"])

                assert result.exit_code == 0, result.output
                assert result.output.startswith("{module_name}\\n")
                assert "├── --help" in result.output
                assert "├── --version" in result.output
                assert "├── --tree" in result.output
                assert "└── --tree-brief" in result.output


            def test_tree_brief_option_prints_registered_cli_tree():
                result = CliRunner().invoke(main, ["--tree-brief"])

                assert result.exit_code == 0, result.output
                assert result.output.startswith("{module_name}\\n")
                assert "├── --tree" in result.output
                assert "└── --tree-brief" in result.output
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_docs_index(package_name: str, docs_domain: str | None = None) -> str:
    docs_url = _chatarch_docs_url(package_name, docs_domain)
    return (
        textwrap.dedent(
            f"""
            # {package_name} 文档

            {package_name} 是 ChatArch 系列 Python 包。这个文档站提供长期维护的使用说明、CLI 树、能力地图和 Python 接口入口。生成模板后，请把占位说明替换为当前包已经实现、探索过或计划中的真实内容。

            站点入口：<{docs_url}>

            ## 按场景选择文档

            | 场景 | 文档 |
            | --- | --- |
            | 第一次安装、运行命令行、确认包可用 | [CLI 树](cli-tree.md) |
            | 校对当前包有哪些一等能力和边界 | [能力地图](capability-map.md) |
            | 从 Python 代码调用包能力 | [Python 接口树](interface-tree.md) |

            ## 文档栏目组织

            当前模板只保留长期有用的文档入口，不生成计划类占位页：

            - **CLI 树**：最直观的命令展示入口，包含真实命令树、状态和更新清单。
            - **能力地图**：当前一等能力、边界和不负责的范围。
            - **接口树**：命令行背后的可 import Python 接口。

            ## 核心入口

            <div class="grid cards" markdown>

            - **CLI 树**

                从命令行入口开始，记录已实现命令、命令状态和交互约定。

                [查看 CLI 树](cli-tree.md)

            - **能力地图**

                用于 review 当前包的能力边界，避免把规划写成已实现功能。

                [查看能力地图](capability-map.md)

            - **Python 接口树**

                保持命令行是薄入口，实质能力放在可 import 的 Python 接口中。

                [查看接口树](interface-tree.md)

            </div>

            ## 文档状态约定

            - **已实现**：代码、测试或 CLI 路径已经存在。
            - **已验证**：已经通过本地 smoke、CI 或真实服务实践验证。
            - **未实现**：只写边界和计划，不写成可执行教程；实现并验证后再升级为操作文档。

            ## 本地预览

            ```bash
            python -m pip install -e ".[docs]"
            mkdocs serve
            ```

            英文首页见站点语言入口：<{docs_url}en/>。缺少英文翻译的专题页会按 i18n fallback 回退到中文页面。
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_docs_index_en(package_name: str, docs_domain: str | None = None) -> str:
    docs_url = _chatarch_docs_url(package_name, docs_domain)
    return (
        textwrap.dedent(
            f"""
            # {package_name} Docs

            {package_name} is a ChatArch Python package. This documentation site should hold long-lived usage notes, a command map, a capability map, and Python interface entry points. After scaffolding, replace placeholders with behavior that is actually implemented, explored, or planned for this package.

            Site entry: <{docs_url}en/>

            ## Choose Documentation by Scenario

            | Scenario | Document |
            | --- | --- |
            | Install the package, run the CLI, and confirm it works | [CLI Tree](cli-tree.md) |
            | Check first-class capabilities and current boundaries | [Capability Map](capability-map.md) |
            | Call package behavior directly from Python | [Python Interface Tree](interface-tree.md) |

            ## Documentation Organization

            This template keeps only durable documentation entry points; it does not generate a plan placeholder:

            - **CLI tree**: the most direct command entry point, including the real command tree, status, and update checklist.
            - **Capability map**: first-class capabilities, boundaries, and out-of-scope areas.
            - **Interface tree**: importable Python APIs behind the CLI.

            ## Primary Entry Points

            <div class="grid cards" markdown>

            - **CLI Tree**

                Start from the CLI entry point and record implemented commands, command status, and interactive conventions.

                [Open CLI Tree](cli-tree.md)

            - **Capability Map**

                Review current package boundaries and avoid presenting planned work as implemented behavior.

                [Open Capability Map](capability-map.md)

            - **Python Interface Tree**

                Keep the CLI thin and put substantive behavior in importable Python APIs.

                [Open Interface Tree](interface-tree.md)

            </div>

            ## Documentation Status

            - **Implemented**: code, tests, or CLI routes exist.
            - **Verified**: covered by local smoke, CI, or real-service practice.
            - **Not implemented**: keep as boundary and planning notes only; turn into operation docs after implementation and validation.

            ## Local Preview

            ```bash
            python -m pip install -e ".[docs]"
            mkdocs serve
            ```

            The Chinese home page is available at <{docs_url}>. Topic pages without English translations fall back to the default Chinese content through the i18n plugin.
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_docs_cli_tree(package_name: str, module_name: str) -> str:
    return (
        textwrap.dedent(
            f"""
            # CLI 能力地图

            这篇文档是 `{package_name}` CLI 的简明能力地图，用来校对哪些命令已经是一等入口、哪些仍然只是边界或规划。生成后请按真实命令树更新；不要把未实现命令写成已可用操作。

            可导入 Python 函数映射见 [接口树](interface-tree.md)。当前包能力边界见 [能力地图](capability-map.md)。

            ## 顶层命令

            ```text
            {module_name}                  # {package_name} 命令行入口
            ├── --help                     # 显示 CLI 帮助和已注册命令
            ├── --version                  # 输出当前包版本
            ├── --tree                     # 输出真实已注册 CLI 树和参数签名
            └── --tree-brief               # 输出命令节点和描述，不含参数签名
            ```

            ## 基础入口

            ```text
            {module_name} --help           # 验证命令已安装，并查看当前命令树
            {module_name} --version        # 验证当前安装版本
            {module_name} --tree           # 回读带参数签名的真实 CLI contract
            {module_name} --tree-brief     # 回读不含参数签名的简明命令树
            ```

            `--help`、`--version`、`--tree` 和 `--tree-brief` 是模板默认可验证入口。两个树选项由 ChatStyle 的 `add_tree_option()` 提供；默认树保留参数签名，简明树只保留命令节点和描述。新增业务命令后，应像 ChatTea 的 CLI 树一样，把命令组单独展开，并给每个命令写一行注释。

            ## 业务命令槽位

            ```text
            {module_name} <group>          # 按当前包真实能力命名的命令组
            ├── <command>                  # 说明这个命令做什么
            └── <command>                  # 说明状态、边界或 checkpoint
            ```

            这里是占位槽位，不是未来能力承诺。只有当命令、Python 函数和测试都存在时，才把它写成已实现入口。

            ## 状态约定

            | 状态 | 含义 |
            | --- | --- |
            | 已实现 | 命令、函数和测试已经存在 |
            | 已验证 | 已通过 CI、本地 smoke 或真实服务实践 |
            | 规划 / checkpoint | 只保留边界说明；实现前不要写操作教程 |

            ## 实现合约

            - 每个已实现命令都要能追到 Python 函数、类或 service 层。
            - 如果命令会写远端状态，文档必须说明凭据、权限、dry-run/checkpoint 或确认边界。
            - 新增命令时，同步更新 README、接口树、能力地图、测试和相关 Flow 页面。
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_docs_cli_tree_en(package_name: str, module_name: str) -> str:
    return (
        textwrap.dedent(
            f"""
            # CLI Capability Map

            This page is the compact capability map for the `{package_name}` CLI. Use it to review which commands are first-class entries and which are still boundary or planned slots. After scaffolding, update it with the real command tree; do not present unimplemented commands as available operations.

            Importable Python functions are mapped in [Interface Tree](interface-tree.md). Current package boundaries are tracked in [Capability Map](capability-map.md).

            ## Top-Level Commands

            ```text
            {module_name}                  # {package_name} command-line entry
            ├── --help                     # Show CLI help and registered commands
            ├── --version                  # Print the current package version
            ├── --tree                     # Print the registered CLI tree with parameter signatures
            └── --tree-brief               # Print command nodes and descriptions without signatures
            ```

            ## Base Entries

            ```text
            {module_name} --help           # Verify the command is installed and inspect the current command tree
            {module_name} --version        # Verify the installed version
            {module_name} --tree           # Read back the CLI contract with parameter signatures
            {module_name} --tree-brief     # Read back command nodes and descriptions only
            ```

            `--help`, `--version`, `--tree`, and `--tree-brief` are the scaffolded verification entries. ChatStyle's `add_tree_option()` provides both tree flags: the default tree keeps parameter signatures, while the brief tree keeps only command nodes and descriptions. After adding business commands, follow the ChatTea CLI tree pattern: split command groups into their own sections and annotate every command line.

            ## Business Command Slots

            ```text
            {module_name} <group>          # Command group named after real package capability
            ├── <command>                  # Explain what this command does
            └── <command>                  # Explain status, boundary, or checkpoint behavior
            ```

            This is a structural placeholder, not a promise of future capability. Only document a command as implemented after the command, Python function, and tests exist.

            ## Status Contract

            | Status | Meaning |
            | --- | --- |
            | Implemented | Command, function, and tests exist |
            | Verified | Covered by CI, local smoke, or real-service practice |
            | Planned / checkpoint | Keep only boundary notes; do not write operation tutorials before implementation |

            ## Implementation Contract

            - Every implemented command must map back to a Python function, class, or service layer.
            - If a command writes remote state, document credentials, permissions, dry-run/checkpoint behavior, or confirmation boundaries.
            - When adding a command, update README, the interface tree, capability map, tests, and related flow pages together.
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_docs_capability_map(package_name: str, module_name: str) -> str:
    return (
        textwrap.dedent(
            f"""
            # 能力地图

            这个页面用于校对 `{package_name}` 当前有哪些一等能力、哪些能力已经验证，以及哪些事情不属于当前包。

            ## 能力分组

            <div class="grid cards" markdown>

            - **命令行入口**

                `{module_name} --help`、`{module_name} --version`、`{module_name} --tree` 和 `{module_name} --tree-brief` 是默认可验证入口。

            - **Python 接口**

                实质能力应放到可 import 的 Python 函数、类或 service 层，而不是只写在 Click 回调里。

            - **配置与环境**

                默认接入 ChatEnv；长期、常用、跨命令共享的配置放入 `config.py`。

            </div>

            ## 当前边界

            | 能力 | 状态 | 说明 |
            | --- | --- | --- |
            | 命令行基础入口 | 已实现 | 模板生成 Click group、`--version`、ChatStyle 共享树选项和基础测试。 |
            | ChatEnv 配置提供者 | 已实现 | 默认生成 `config.py` 和 `chatenv.configs` 入口点。 |
            | 业务命令 | 未实现 | 按当前包真实需求补充，不能在模板里伪造未来命令。 |

            ## 不在当前范围

            - 不生成计划类占位页。
            - 不把未实现能力写成用户可执行教程。
            - 不在 README、docs、issue、PR 评论或 CI log 中输出 secret、token、cookie 或 Authorization header。
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_docs_capability_map_en(package_name: str, module_name: str) -> str:
    return (
        textwrap.dedent(
            f"""
            # Capability Map

            Use this page to check which first-class capabilities `{package_name}` currently owns, which ones are verified, and what remains out of scope for this package.

            ## Capability Groups

            <div class="grid cards" markdown>

            - **CLI Entry**

                `{module_name} --help`, `{module_name} --version`, `{module_name} --tree`, and `{module_name} --tree-brief` are the default verification entry points.

            - **Python API**

                Substantive behavior should live in importable Python functions, classes, or service layers rather than only in Click callbacks.

            - **Config and Environment**

                ChatEnv integration is enabled by default; stable, shared configuration belongs in `config.py`.

            </div>

            ## Current Boundary

            | Capability | Status | Notes |
            | --- | --- | --- |
            | CLI base entry | Implemented | The template generates a Click group, `--version`, shared ChatStyle tree options, and base tests. |
            | ChatEnv provider | Implemented | The template generates `config.py` and a `chatenv.configs` entry point. |
            | Business commands | Not implemented | Add these from the real package domain; do not fake future commands in the template. |

            ## Out of Scope

            - No plan placeholder page is generated.
            - No unimplemented capability should be written as a user operation tutorial.
            - No secret, token, cookie, or Authorization header should appear in README, docs, issues, PR comments, or CI logs.
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_docs_interface_tree(package_name: str, module_name: str) -> str:
    return (
        textwrap.dedent(
            f"""
            # Python 接口树

            `{package_name}` 的 CLI 应保持薄入口；实质能力应放在可 import 的 Python 函数、类或 service 层里。

            ## 包入口

            ```python
            from {module_name} import __version__
            ```

            ## 待补接口

            ```text
            {module_name}
            ├── cli.py          # Click 入口，只做参数解析和输出
            └── <service>.py    # 放包的核心可调用能力
            ```

            ## 更新清单

            - 每个实质 CLI 命令都要能映射到 importable API。
            - 文档里的函数签名应和代码一致。
            - 对外输出默认不要泄漏 token、cookie、内部 URL 或人员信息。
            """
        ).strip()
        + "\n"
    )


def _build_chatarch_mkdocs_yml(package_name: str, docs_domain: str | None = None) -> str:
    repo_slug = _chatarch_repo_slug(package_name)
    docs_url = _chatarch_docs_url(package_name, docs_domain)
    return (
        textwrap.dedent(
            f"""
            site_name: {package_name} 文档
            site_url: {docs_url}
            repo_url: https://github.com/{repo_slug}
            repo_name: {repo_slug}
            edit_uri: edit/main/docs/
            docs_dir: docs/
            theme:
              name: material
              language: zh
              features:
                - navigation.tabs
                - navigation.sections
                - navigation.expand
                - navigation.top
                - search.highlight
                - search.share
                - content.code.copy
                - content.action.edit
            plugins:
              - search
              - i18n:
                  docs_structure: suffix
                  fallback_to_default: true
                  reconfigure_material: true
                  reconfigure_search: true
                  languages:
                    - locale: zh
                      default: true
                      name: 中文
                      build: true
                      site_name: {package_name} 文档
                    - locale: en
                      name: English
                      build: true
                      site_name: {package_name} Documentation
                      nav_translations:
                        首页: Home
                        命令与接口: Commands and APIs
                        CLI 树: CLI Tree
                        能力地图: Capability Map
                        Python 接口树: Python Interface Tree
            markdown_extensions:
              - admonition
              - attr_list
              - md_in_html
              - toc:
                  permalink: true
              - pymdownx.superfences
              - pymdownx.inlinehilite
              - pymdownx.highlight:
                  anchor_linenums: true
              - pymdownx.emoji:
                  emoji_index: !!python/name:material.extensions.emoji.twemoji
                  emoji_generator: !!python/name:material.extensions.emoji.to_svg
            extra:
              alternate:
                - name: 中文
                  link: /{package_name}/
                  lang: zh
                - name: English
                  link: /{package_name}/en/
                  lang: en
            nav:
              - 首页: index.md
              - 命令与接口:
                  - CLI 树: cli-tree.md
                  - 能力地图: capability-map.md
                  - Python 接口树: interface-tree.md
            """
        ).strip()
        + "\n"
    )



def _build_chatarch_agends_md() -> str:
    return (
        textwrap.dedent(
            """
            # Agent Notes

            ## Development Expectations

            - Keep changes minimal and reviewable.
            - Prefer doc-first CLI tests.
            - Sync docs and changelog with user-facing behavior.
            - Use interactive prompts only when arguments are missing and recoverable.
            """
        ).strip()
        + "\n"
    )


def scaffold_package(
    package_name: str,
    project_dir: Path,
    *,
    initial_version: str = "0.1.0",
    description: str | None = None,
    requires_python: str = ">=3.9",
    license_name: str = "MIT",
    author: str | None = None,
    email: str | None = None,
    template: str = "default",
    include_mkdocs: bool | None = None,
    include_workflows: bool | None = None,
    include_chatenv_provider: bool | None = None,
    chatenv_provider_name: str | None = None,
    docs_domain: str | None = None,
) -> ScaffoldResult:
    package_name = package_name.strip()
    if not package_name:
        raise PyPICommandError("Package name is required.")
    if template == "chatarch" and requires_python == ">=3.9":
        requires_python = ">=3.10"
    if include_mkdocs is None:
        include_mkdocs = template == "chatarch"
    if include_workflows is None:
        include_workflows = template == "chatarch"
    if include_chatenv_provider is None:
        include_chatenv_provider = template == "chatarch"
    resolved_docs_domain = _normalize_docs_domain(docs_domain) if include_mkdocs else None
    if chatenv_provider_name and not include_chatenv_provider:
        raise PyPICommandError(
            "chatenv_provider_name requires include_chatenv_provider=True."
        )
    if include_chatenv_provider and template != "chatarch":
        raise PyPICommandError(
            "include_chatenv_provider is only supported by the chatarch template."
        )

    module_name = normalize_module_name(package_name)
    resolved_chatenv_provider_name = (
        normalize_module_name(chatenv_provider_name or module_name)
        if include_chatenv_provider
        else None
    )
    workflow_python_version = _workflow_python_version(requires_python)
    project_dir = Path(project_dir)
    _ensure_empty_or_missing(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    description = description or f"{package_name} package"
    src_dir = project_dir / "src" / module_name
    tests_dir = project_dir / "tests"
    created_files: list[Path] = []

    src_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    file_map = {
        project_dir / "pyproject.toml": _build_pyproject_content(
            package_name=package_name,
            module_name=module_name,
            description=description,
            requires_python=requires_python,
            license_name=license_name,
            author=author,
            email=email,
        ),
        project_dir / "README.md": textwrap.dedent(f"""
            # {package_name}

            {description}

            ## Quick Start

            ```bash
            chattool pypi build --project-dir .
            chattool pypi check --project-dir .
            chattool pypi upload --project-dir .
            ```
        """).strip()
        + "\n",
        project_dir / "LICENSE": _license_template_content(license_name, author),
        project_dir / ".gitignore": textwrap.dedent("""
            __pycache__/
            .pytest_cache/
            .venv/
            build/
            dist/
            site/
            *.egg-info/
        """).strip()
        + "\n",
        src_dir / "__init__.py": textwrap.dedent(f'''
            """{package_name} package."""

            __all__ = ["__version__"]

            __version__ = "{initial_version}"
        ''').strip()
        + "\n",
        tests_dir / "conftest.py": textwrap.dedent("""
            from pathlib import Path
            import sys


            ROOT = Path(__file__).resolve().parents[1]
            SRC = ROOT / "src"
            if str(SRC) not in sys.path:
                sys.path.insert(0, str(SRC))
        """).strip()
        + "\n",
        tests_dir / "test_version.py": textwrap.dedent(f"""
            from {module_name} import __version__


            def test_version_present():
                assert __version__ == "{initial_version}"
        """).strip()
        + "\n",
    }

    if template == "chatarch":
        (tests_dir / "cli-tests").mkdir(parents=True, exist_ok=True)
        (tests_dir / "mock-cli-tests").mkdir(parents=True, exist_ok=True)
        (tests_dir / "code-tests").mkdir(parents=True, exist_ok=True)
        if include_mkdocs:
            (project_dir / "docs").mkdir(parents=True, exist_ok=True)
        if include_workflows:
            (project_dir / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        file_map.update(
            {
                project_dir / "pyproject.toml": _build_chatarch_pyproject_content(
                    package_name=package_name,
                    module_name=module_name,
                    description=description,
                    requires_python=requires_python,
                    license_name=license_name,
                    author=author,
                    email=email,
                    include_mkdocs=include_mkdocs,
                    chatenv_provider_name=resolved_chatenv_provider_name,
                    docs_domain=resolved_docs_domain,
                ),
                project_dir / "README.md": _build_chatarch_readme(
                    package_name,
                    module_name,
                    description,
                    include_mkdocs=include_mkdocs,
                    include_workflows=include_workflows,
                    docs_domain=resolved_docs_domain,
                ),
                project_dir / "README.en.md": _build_chatarch_readme_en(
                    package_name,
                    module_name,
                    description,
                    include_mkdocs=include_mkdocs,
                    include_workflows=include_workflows,
                    docs_domain=resolved_docs_domain,
                ),
                project_dir / "DEVELOP.md": _build_chatarch_develop_md(),
                project_dir / "CHANGELOG.md": _build_chatarch_changelog(),
                project_dir / "AGENTS.md": _build_chatarch_agends_md(),
                project_dir / "mkdocs.yml": _build_chatarch_mkdocs_yml(
                    package_name,
                    docs_domain=resolved_docs_domain,
                ),
                project_dir / "docs" / "index.md": _build_chatarch_docs_index(
                    package_name,
                    docs_domain=resolved_docs_domain,
                ),
                project_dir / "docs" / "index.en.md": _build_chatarch_docs_index_en(
                    package_name,
                    docs_domain=resolved_docs_domain,
                ),
                project_dir / "docs" / "cli-tree.md": _build_chatarch_docs_cli_tree(
                    package_name,
                    module_name,
                ),
                project_dir / "docs" / "cli-tree.en.md": _build_chatarch_docs_cli_tree_en(
                    package_name,
                    module_name,
                ),
                project_dir / "docs" / "capability-map.md": _build_chatarch_docs_capability_map(
                    package_name,
                    module_name,
                ),
                project_dir / "docs" / "capability-map.en.md": _build_chatarch_docs_capability_map_en(
                    package_name,
                    module_name,
                ),
                project_dir / "docs" / "interface-tree.md": _build_chatarch_docs_interface_tree(
                    package_name,
                    module_name,
                ),
                tests_dir
                / "cli-tests"
                / "README.md": "# CLI Tests\n\nReal CLI tests live here.\n",
                tests_dir
                / "mock-cli-tests"
                / "README.md": "# Mock CLI Tests\n\nMock/fake CLI tests live here.\n",
                tests_dir
                / "code-tests"
                / "README.md": "# Code Tests\n\nNon-CLI code tests live here.\n",
                src_dir / "cli.py": _build_chatarch_cli_py(module_name),
                tests_dir / "test_cli.py": _build_chatarch_test_cli_py(module_name),
                project_dir / ".github" / "workflows" / "ci.yml": textwrap.dedent(
                    """
                    name: CI

                    on:
                      push:
                        branches:
                          - main
                          - master
                      pull_request:

                    jobs:
                      test:
                        runs-on: ubuntu-latest
                        steps:
                          - uses: actions/checkout@v4
                          - name: Configure Git Credentials
                            run: |
                              git config user.name github-actions[bot]
                              git config user.email 41898282+github-actions[bot]@users.noreply.github.com
                          - uses: actions/setup-python@v5
                            with:
                              python-version: "{workflow_python_version}"
                          - run: python -m pip install --upgrade pip
                          - run: python -m pip install -e ".[dev,docs]"
                          - run: python -m pytest -q
                          - run: python -m {module_name}.cli --version
                          - run: python -m {module_name}.cli --tree
                          - run: python -m {module_name}.cli --tree-brief
                          - run: python -m build
                          - run: mkdocs build --strict
                    """
                )
                .replace("{workflow_python_version}", workflow_python_version)
                .replace("{module_name}", module_name)
                .strip()
                + "\n",
                project_dir / ".github" / "workflows" / "publish.yml": textwrap.dedent(
                    """
                    name: Publish Package

                    on:
                      push:
                        tags:
                          - "v*"

                    permissions:
                      contents: read

                    jobs:
                      publish:
                        runs-on: ubuntu-latest
                        permissions:
                          contents: read
                          id-token: write
                        steps:
                          - uses: actions/checkout@v4
                            with:
                              fetch-depth: 0
                          - uses: actions/setup-python@v5
                            with:
                              python-version: "{workflow_python_version}"
                          - name: Resolve package version
                            id: meta
                            run: |
                              python - <<'PY'
                              import ast
                              import os
                              from pathlib import Path

                              module = ast.parse(Path("src/{module_name}/__init__.py").read_text(encoding="utf-8"))
                              for stmt in module.body:
                                  if not isinstance(stmt, ast.Assign):
                                      continue
                                  if any(isinstance(target, ast.Name) and target.id == "__version__" for target in stmt.targets):
                                      version = ast.literal_eval(stmt.value)
                                      break
                              else:
                                  raise SystemExit("__version__ not found in src/{module_name}/__init__.py")

                              with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                                  print(f"version={version}", file=output)
                                  print(f"tag=v{version}", file=output)
                              PY
                          - name: Verify tag matches package version
                            env:
                              RELEASE_TAG: ${{ steps.meta.outputs.tag }}
                            run: |
                              if [ "${GITHUB_REF_NAME}" != "${RELEASE_TAG}" ]; then
                                echo "Tag ${GITHUB_REF_NAME} does not match package version ${RELEASE_TAG}."
                                exit 1
                              fi
                          - name: Check tag commit is on main
                            run: |
                              git fetch --no-tags origin main:refs/remotes/origin/main
                              git merge-base --is-ancestor "${GITHUB_SHA}" refs/remotes/origin/main
                          - name: Check PyPI version
                            id: pypi
                            env:
                              PACKAGE_NAME: "{package_name}"
                              PACKAGE_VERSION: ${{ steps.meta.outputs.version }}
                            run: |
                              python - <<'PY'
                              import os
                              import urllib.error
                              import urllib.parse
                              import urllib.request

                              package = os.environ["PACKAGE_NAME"]
                              version = os.environ["PACKAGE_VERSION"]
                              url = f"https://pypi.org/pypi/{urllib.parse.quote(package)}/{urllib.parse.quote(version)}/json"
                              exists = "false"
                              try:
                                  urllib.request.urlopen(url, timeout=10)
                              except urllib.error.HTTPError as exc:
                                  if exc.code != 404:
                                      raise
                              else:
                                  exists = "true"

                              with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                                  print(f"exists={exists}", file=output)
                              PY
                          - name: Stop when version is already on PyPI
                            if: steps.pypi.outputs.exists == 'true'
                            run: echo "{package_name} ${{ steps.meta.outputs.version }} is already on PyPI; skipping publish."
                          - name: Build distribution
                            if: steps.pypi.outputs.exists == 'false'
                            run: |
                              python -m pip install --upgrade pip build twine
                              python -m build
                              python -m twine check dist/*
                          - name: Publish to PyPI
                            if: steps.pypi.outputs.exists == 'false'
                            uses: pypa/gh-action-pypi-publish@release/v1
                    """
                )
                .replace("{workflow_python_version}", workflow_python_version)
                .replace("{package_name}", package_name)
                .replace("{module_name}", module_name)
                .strip()
                + "\n",
                project_dir / ".github" / "workflows" / "deploy.yaml": textwrap.dedent(
                    """
                    name: Deploy Docs

                    on:
                      push:
                        branches:
                          - main
                          - master

                    permissions:
                      contents: write

                    jobs:
                      deploy:
                        runs-on: ubuntu-latest
                        steps:
                          - uses: actions/checkout@v4
                          - uses: actions/setup-python@v5
                            with:
                              python-version: "{workflow_python_version}"
                          - run: python -m pip install --upgrade pip
                          - run: python -m pip install -e ".[docs]"
                          - run: mkdocs gh-deploy --force
                    """
                )
                .replace("{workflow_python_version}", workflow_python_version)
                .strip()
                + "\n",
                project_dir / ".github" / "workflows" / "preview.yaml": textwrap.dedent(
                    """
                    name: Preview Docs

                    on:
                      pull_request:
                        branches:
                          - main
                          - master

                    permissions:
                      contents: write
                      pull-requests: write

                    jobs:
                      deploy:
                        runs-on: ubuntu-latest
                        if: ${{ !github.event.pull_request.head.repo.fork }}
                        steps:
                          - uses: actions/checkout@v4
                          - name: Configure Git Credentials
                            run: |
                              git config user.name github-actions[bot]
                              git config user.email 41898282+github-actions[bot]@users.noreply.github.com
                          - uses: actions/setup-python@v5
                            with:
                              python-version: "{workflow_python_version}"
                          - run: python -m pip install --upgrade pip
                          - run: python -m pip install -e ".[docs]"
                          - name: Deploy preview docs
                            run: |
                              git fetch origin gh-pages --depth=1 || true
                              mike deploy dev --push --update-aliases --allow-empty
                              site_url=$(python - <<'PY'
                              from pathlib import Path

                              for line in Path("mkdocs.yml").read_text(encoding="utf-8").splitlines():
                                  if line.startswith("site_url:"):
                                      print(line.split(":", 1)[1].strip().rstrip("/"))
                                      break
                              else:
                                  raise SystemExit("mkdocs.yml is missing site_url")
                              PY
                              )
                              preview_url="${site_url}/dev/"
                              echo "CHATARCH_PREVIEW_URL=${preview_url}" >> "$GITHUB_ENV"
                              echo "Preview URL: ${preview_url}" >> "$GITHUB_STEP_SUMMARY"

                          - name: Comment PR with Preview Link
                            uses: actions/github-script@v6
                            with:
                              script: |
                                const { payload } = context;
                                const previewLink = process.env.CHATARCH_PREVIEW_URL;
                                const comments = await github.rest.issues.listComments({
                                  owner: context.repo.owner,
                                  repo: context.repo.repo,
                                  issue_number: payload.number,
                                });
                                const existingComment = comments.data.find(comment => comment.body.includes(previewLink));
                                if (!existingComment) {
                                  await github.rest.issues.createComment({
                                    owner: context.repo.owner,
                                    repo: context.repo.repo,
                                    issue_number: payload.number,
                                    body: `Preview available at: ${previewLink}`,
                                  });
                                }
                    """
                )
                .replace("{workflow_python_version}", workflow_python_version)
                .replace("{docs_domain}", resolved_docs_domain or DEFAULT_CHATARCH_DOCS_DOMAIN)
                .strip()
                + "\n",
            }
        )
        if resolved_chatenv_provider_name:
            file_map[src_dir / "config.py"] = _build_chatarch_chatenv_config_py(
                package_name=package_name,
                module_name=module_name,
                provider_name=resolved_chatenv_provider_name,
            )
        if not include_mkdocs:
            for optional_path in (
                project_dir / "mkdocs.yml",
                project_dir / "docs" / "index.md",
                project_dir / "docs" / "index.en.md",
                project_dir / "docs" / "cli-tree.md",
                project_dir / "docs" / "cli-tree.en.md",
                project_dir / "docs" / "capability-map.md",
                project_dir / "docs" / "capability-map.en.md",
                project_dir / "docs" / "interface-tree.md",
                project_dir / ".github" / "workflows" / "deploy.yaml",
                project_dir / ".github" / "workflows" / "preview.yaml",
            ):
                file_map.pop(optional_path, None)
            ci_path = project_dir / ".github" / "workflows" / "ci.yml"
            if ci_path in file_map:
                file_map[ci_path] = file_map[ci_path].replace(
                    'python -m pip install -e ".[dev,docs]"',
                    'python -m pip install -e ".[dev]"',
                ).replace("\n                          - run: mkdocs build --strict", "")
        if not include_workflows:
            for optional_path in list(file_map):
                if ".github" in optional_path.parts:
                    file_map.pop(optional_path, None)

    for path, content in file_map.items():
        path.write_text(content, encoding="utf-8")
        created_files.append(path)

    return ScaffoldResult(
        project_dir=project_dir,
        package_name=package_name,
        module_name=module_name,
        created_files=sorted(created_files),
    )


def _load_pyproject(project_dir: Path) -> dict:
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        raise PyPICommandError(f"pyproject.toml not found under {project_dir}")
    try:
        return tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover
        raise PyPICommandError(f"Failed to parse {pyproject_path}: {exc}") from exc


def _extract_license_text(license_value) -> str | None:
    if isinstance(license_value, str):
        return license_value
    if isinstance(license_value, dict):
        if license_value.get("text"):
            return str(license_value["text"])
        if license_value.get("file"):
            return f"file:{license_value['file']}"
    return None


def _extract_readme_path(readme_value) -> str | None:
    if isinstance(readme_value, str):
        return readme_value
    if isinstance(readme_value, dict) and readme_value.get("file"):
        return str(readme_value["file"])
    return None


def _resolve_dynamic_version_source(
    pyproject: dict, dynamic_fields: list[str]
) -> str | None:
    if "version" not in dynamic_fields:
        return None
    tool_data = pyproject.get("tool", {})
    setuptools_data = (
        tool_data.get("setuptools", {}) if isinstance(tool_data, dict) else {}
    )
    dynamic_data = (
        setuptools_data.get("dynamic", {}) if isinstance(setuptools_data, dict) else {}
    )
    version_data = (
        dynamic_data.get("version") if isinstance(dynamic_data, dict) else None
    )
    if isinstance(version_data, dict):
        if version_data.get("attr"):
            return f"dynamic via attr={version_data['attr']}"
        if version_data.get("file"):
            return f"dynamic via file={version_data['file']}"
    return "dynamic"


def _load_attr_version(project_dir: Path, attr_path: str) -> str | None:
    module_path, _, attribute = attr_path.rpartition(".")
    if not module_path or not attribute:
        return None
    relative_parts = module_path.split(".")
    candidate_files = []
    for base_dir in (project_dir / "src", project_dir):
        candidate_files.append(base_dir.joinpath(*relative_parts, "__init__.py"))
        candidate_files.append(base_dir.joinpath(*relative_parts).with_suffix(".py"))

    for candidate in candidate_files:
        if not candidate.exists():
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"_chattool_pypi_dynamic_{candidate.stem}_{abs(hash(candidate))}",
                candidate,
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            value = getattr(module, attribute, None)
        except Exception:  # pragma: no cover
            continue
        if value is not None:
            return str(value)
    return None


def _load_file_version(project_dir: Path, relative_path: str) -> str | None:
    target = project_dir / relative_path
    if not target.exists():
        return None
    content = target.read_text(encoding="utf-8").strip()
    return content or None


def _resolve_dynamic_version_value(
    project_dir: Path, pyproject: dict, dynamic_fields: list[str]
) -> str | None:
    if "version" not in dynamic_fields:
        return None
    tool_data = pyproject.get("tool", {})
    setuptools_data = (
        tool_data.get("setuptools", {}) if isinstance(tool_data, dict) else {}
    )
    dynamic_data = (
        setuptools_data.get("dynamic", {}) if isinstance(setuptools_data, dict) else {}
    )
    version_data = (
        dynamic_data.get("version") if isinstance(dynamic_data, dict) else None
    )
    if isinstance(version_data, dict):
        attr_path = version_data.get("attr")
        if isinstance(attr_path, str):
            return _load_attr_version(project_dir, attr_path)
        file_path = version_data.get("file")
        if isinstance(file_path, str):
            return _load_file_version(project_dir, file_path)
    return None


def read_project_metadata(project_dir: Path) -> ProjectMetadata:
    pyproject = _load_pyproject(project_dir)
    project_data = pyproject.get("project")
    if not isinstance(project_data, dict):
        raise PyPICommandError("Missing [project] table in pyproject.toml")

    dynamic_fields = [
        field for field in project_data.get("dynamic", []) if isinstance(field, str)
    ]
    version = project_data.get("version")
    version_source = None
    if not version:
        version_source = _resolve_dynamic_version_source(pyproject, dynamic_fields)
        version = _resolve_dynamic_version_value(project_dir, pyproject, dynamic_fields)

    return ProjectMetadata(
        name=project_data.get("name"),
        version=version if isinstance(version, str) else None,
        version_source=version_source,
        readme=_extract_readme_path(project_data.get("readme")),
        requires_python=project_data.get("requires-python"),
        license_text=_extract_license_text(project_data.get("license")),
        dynamic_fields=dynamic_fields,
    )


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _find_license_file(project_dir: Path) -> Path | None:
    for candidate in ("LICENSE", "LICENSE.txt", "LICENSE.md"):
        path = project_dir / candidate
        if path.exists():
            return path
    return None


def collect_doctor_checks(
    project_dir: Path, dist_dir: Path | None = None
) -> list[DoctorCheck]:
    project_dir = Path(project_dir)
    dist_dir = resolve_dist_dir(project_dir, dist_dir)
    pyproject_path = project_dir / "pyproject.toml"

    checks: list[DoctorCheck] = []
    if not pyproject_path.exists():
        return [
            DoctorCheck(
                label="pyproject.toml",
                status="fail",
                detail=f"missing: {pyproject_path}",
                hint="Create pyproject.toml before using chattool pypi.",
            )
        ]

    checks.append(DoctorCheck("pyproject.toml", "ok", f"found: {pyproject_path.name}"))

    try:
        metadata = read_project_metadata(project_dir)
    except PyPICommandError as exc:
        checks.append(DoctorCheck("project metadata", "fail", str(exc)))
        return checks

    checks.append(
        DoctorCheck(
            "project.name",
            "ok" if metadata.name else "fail",
            metadata.name or "missing [project].name",
        )
    )
    if metadata.version:
        version_detail = metadata.version
        if metadata.version_source:
            version_detail = f"{metadata.version} ({metadata.version_source})"
        status = "ok"
    elif metadata.version_source:
        version_detail = metadata.version_source
        status = "ok"
    else:
        version_detail = "missing version or dynamic version configuration"
        status = "fail"
    checks.append(DoctorCheck("project.version", status, version_detail))
    checks.append(
        DoctorCheck(
            "project.readme",
            "ok" if metadata.readme else "fail",
            metadata.readme or "missing [project].readme",
        )
    )
    checks.append(
        DoctorCheck(
            "project.requires-python",
            "ok" if metadata.requires_python else "fail",
            metadata.requires_python or "missing [project].requires-python",
        )
    )
    checks.append(
        DoctorCheck(
            "project.license",
            "ok" if metadata.license_text else "fail",
            metadata.license_text or "missing [project].license",
        )
    )

    if metadata.readme:
        readme_path = project_dir / metadata.readme
        checks.append(
            DoctorCheck(
                "README file",
                "ok" if readme_path.exists() else "fail",
                str(readme_path.relative_to(project_dir))
                if readme_path.exists()
                else f"missing: {metadata.readme}",
            )
        )

    license_path = _find_license_file(project_dir)
    build_available = _module_available("build")
    twine_available = _module_available("twine")

    checks.append(
        DoctorCheck(
            "LICENSE file",
            "ok" if license_path else "fail",
            license_path.name
            if license_path
            else "missing LICENSE / LICENSE.txt / LICENSE.md",
        )
    )
    checks.append(
        DoctorCheck(
            "build module",
            "ok" if build_available else "fail",
            "installed" if build_available else "python -m build unavailable",
            hint='Install with `pip install build` or `pip install "chattool[pypi]"`.',
        )
    )
    checks.append(
        DoctorCheck(
            "twine module",
            "ok" if twine_available else "fail",
            "installed" if twine_available else "python -m twine unavailable",
            hint='Install with `pip install twine` or `pip install "chattool[pypi]"`.',
        )
    )

    existing_artifacts = find_distributions(dist_dir)
    if existing_artifacts:
        checks.append(
            DoctorCheck(
                "dist artifacts",
                "warn",
                f"{len(existing_artifacts)} existing file(s) under {dist_dir}",
                hint="Use `chattool pypi build --clean` to replace old build artifacts.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "dist artifacts", "ok", f"no existing artifacts under {dist_dir}"
            )
        )
    return checks


def doctor_has_failures(checks: list[DoctorCheck]) -> bool:
    return any(check.status == "fail" for check in checks)


def find_distributions(dist_dir: Path) -> list[Path]:
    dist_dir = Path(dist_dir)
    if not dist_dir.exists():
        return []
    found: list[Path] = []
    for pattern in ("*.whl", "*.tar.gz", "*.zip"):
        found.extend(dist_dir.glob(pattern))
    return sorted(set(path.resolve() for path in found))


def _repository_json_base(repository: str, repository_url: str | None = None) -> str:
    if repository_url:
        parsed = urllib_parse.urlparse(repository_url)
        host = parsed.netloc.lower()
        if host == "upload.pypi.org":
            return "https://pypi.org"
        if host == "test.pypi.org":
            return "https://test.pypi.org"
        return f"{parsed.scheme}://{parsed.netloc}"
    if repository == "pypi":
        return "https://pypi.org"
    return "https://test.pypi.org"


def _fetch_repository_json(url: str, timeout: float = 5.0) -> tuple[int, dict | None]:
    request = urllib_request.Request(
        url,
        headers={"Accept": "application/json"},
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return response.status, json.loads(payload)
    except urllib_error.HTTPError as exc:
        if exc.code == 404:
            return 404, None
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise PyPICommandError(
            f"Repository query failed for {url}: HTTP {exc.code} {detail or exc.reason}"
        ) from exc
    except urllib_error.URLError as exc:
        raise PyPICommandError(
            f"Repository query failed for {url}: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise PyPICommandError(f"Repository query failed for {url}: timeout") from exc
    except json.JSONDecodeError as exc:
        raise PyPICommandError(
            f"Repository query returned invalid JSON for {url}: {exc}"
        ) from exc


def check_repository_conflicts(
    package_name: str,
    *,
    repository: str = "pypi",
    repository_url: str | None = None,
    timeout: float = 5.0,
    fetcher=_fetch_repository_json,
) -> list[RepositoryCheck]:
    package_name = package_name.strip()
    if not package_name:
        raise PyPICommandError(
            "Package name is required for repository conflict checks."
        )

    base_url = _repository_json_base(repository, repository_url)
    package_url = f"{base_url}/pypi/{urllib_parse.quote(package_name)}/json"
    package_status, payload = fetcher(package_url, timeout=timeout)
    target_label = repository_url or repository

    checks: list[RepositoryCheck] = []
    if package_status == 404:
        return [
            RepositoryCheck(
                label="package name",
                status="ok",
                detail=f"{package_name} is available on {target_label}",
                hint="Exact project-name check. This does not use PyPI search results.",
            ),
            RepositoryCheck(
                label="result",
                status="ok",
                detail=f"name is available on {target_label}",
                hint="Use this as a first-pass name check before publishing.",
            ),
        ]
    else:
        checks.append(
            RepositoryCheck(
                label="package name",
                status="fail",
                detail=f"{package_name} already exists on {target_label}",
                hint="Choose another package name for a new package. Only keep this name if you own the existing project.",
            )
        )
        checks.append(
            RepositoryCheck(
                label="result",
                status="fail",
                detail=f"blocked for a new package: {package_name} already exists on {target_label}",
                hint="Choose another package name unless you own the existing project.",
            )
        )
        checks.extend(_extract_project_snippets(payload))
    return checks


def _clean_dist_dir(dist_dir: Path) -> None:
    if not dist_dir.exists():
        return
    for path in dist_dir.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()


def run_command(
    args: list[str], cwd: Path, env: dict[str, str] | None = None
) -> CommandResult:
    logger.info("Running command", extra={"command_args": args, "cwd": str(cwd)})
    process = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    logger.info(
        "Command finished",
        extra={"command_args": args, "cwd": str(cwd), "returncode": process.returncode},
    )
    return CommandResult(
        args=list(args),
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def _ensure_success(result: CommandResult, action: str) -> CommandResult:
    if result.returncode == 0:
        return result
    detail = result.stderr.strip() or result.stdout.strip() or "no output"
    raise PyPICommandError(f"{action} failed: {detail}")


def build_package(
    project_dir: Path,
    dist_dir: Path | None = None,
    *,
    clean: bool = True,
    sdist: bool = False,
    wheel: bool = False,
    runner=run_command,
) -> tuple[CommandResult, list[Path]]:
    project_dir = Path(project_dir)
    dist_dir = resolve_dist_dir(project_dir, dist_dir)
    if not (project_dir / "pyproject.toml").exists():
        raise PyPICommandError(f"pyproject.toml not found under {project_dir}")

    if clean:
        _clean_dist_dir(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)

    args = [sys.executable, "-m", "build", "--outdir", str(dist_dir)]
    if sdist and not wheel:
        args.append("--sdist")
    elif wheel and not sdist:
        args.append("--wheel")

    logger.info(
        "Building package distributions",
        extra={"project_dir": str(project_dir), "dist_dir": str(dist_dir)},
    )
    result = _ensure_success(runner(args, project_dir), "Build")
    files = find_distributions(dist_dir)
    if not files:
        logger.error(
            "Build completed without distributions",
            extra={"project_dir": str(project_dir), "dist_dir": str(dist_dir)},
        )
        raise PyPICommandError(
            f"Build completed but no distributions were found under {dist_dir}"
        )
    logger.info(
        "Built package distributions",
        extra={
            "project_dir": str(project_dir),
            "dist_dir": str(dist_dir),
            "artifact_count": len(files),
        },
    )
    return result, files


def check_distributions(
    project_dir: Path,
    dist_dir: Path | None = None,
    *,
    strict: bool = False,
    runner=run_command,
) -> tuple[CommandResult, list[Path]]:
    project_dir = Path(project_dir)
    dist_dir = resolve_dist_dir(project_dir, dist_dir)
    files = find_distributions(dist_dir)
    if not files:
        raise PyPICommandError(
            f"No distributions found under {dist_dir}. Run `chatpypi build` first."
        )

    args = [sys.executable, "-m", "twine", "check"]
    if strict:
        args.append("--strict")
    args.extend(str(path) for path in files)
    logger.info(
        "Checking package distributions",
        extra={
            "project_dir": str(project_dir),
            "dist_dir": str(dist_dir),
            "artifact_count": len(files),
        },
    )
    result = _ensure_success(runner(args, project_dir), "Twine check")
    logger.info(
        "Checked package distributions",
        extra={
            "project_dir": str(project_dir),
            "dist_dir": str(dist_dir),
            "artifact_count": len(files),
        },
    )
    return result, files


def upload_distributions(
    project_dir: Path,
    dist_dir: Path | None = None,
    *,
    skip_existing: bool = False,
    repository: str = "pypi",
    repository_url: str | None = None,
    username: str | None = None,
    env: dict[str, str] | None = None,
    runner=run_command,
) -> tuple[CommandResult, list[Path]]:
    project_dir = Path(project_dir)
    dist_dir = resolve_dist_dir(project_dir, dist_dir)
    files = find_distributions(dist_dir)
    if not files:
        raise PyPICommandError(
            f"No distributions found under {dist_dir}. Run `chatpypi build` first."
        )

    args = [sys.executable, "-m", "twine", "upload"]
    if skip_existing:
        args.append("--skip-existing")
    if repository_url:
        args.extend(["--repository-url", repository_url])
    elif repository != "pypi":
        args.extend(["--repository", repository])
    if username:
        args.extend(["--username", username])
    args.extend(str(path) for path in files)
    logger.info(
        "Uploading package distributions",
        extra={
            "project_dir": str(project_dir),
            "dist_dir": str(dist_dir),
            "artifact_count": len(files),
        },
    )
    if env is None:
        result = runner(args, project_dir)
    else:
        result = runner(args, project_dir, env=env)
    secrets = [
        (env or {}).get("TWINE_PASSWORD", ""),
        (env or {}).get("PYPI_API_TOKEN", ""),
        (env or {}).get("PYPI_TOKEN", ""),
    ]
    secrets = [value for value in secrets if value]
    if secrets:
        stdout = result.stdout
        stderr = result.stderr
        for secret in secrets:
            stdout = stdout.replace(secret, "[REDACTED]")
            stderr = stderr.replace(secret, "[REDACTED]")
        result = CommandResult(
            args=result.args,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    result = _ensure_success(result, "Twine upload")
    logger.info(
        "Uploaded package distributions",
        extra={
            "project_dir": str(project_dir),
            "dist_dir": str(dist_dir),
            "artifact_count": len(files),
        },
    )
    return result, files
