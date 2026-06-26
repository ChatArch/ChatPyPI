<div align="center">
    <a href="https://pypi.python.org/pypi/ChatPyPI">
        <img src="https://img.shields.io/pypi/v/ChatPyPI.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/ChatPyPI/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/ChatPyPI/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
    <a href="https://ChatArch.github.io/ChatPyPI">
        <img src="https://img.shields.io/badge/docs-mkdocs-blue.svg" alt="Documentation" />
    </a>
</div>

<div align="center">

[English](README.en.md) | [简体中文](README.md)
</div>

# ChatPyPI

ChatPyPI: ChatArch Python package lifecycle helper extracted from ChatTool.

## Quick Start

```bash
pip install -e ".[dev]"
chatpypi --help
chatpypi pkg init demo-pkg
python -m pytest -q
python -m build
```

## Current CLI Tree

`ChatPyPI` is growing from a package lifecycle helper into a combined
"package + post-registration PyPI operations" CLI. The current public tree now
reserves:

- `chatpypi pkg`
- `chatpypi auth`
- `chatpypi profile`
- `chatpypi config`
- `chatpypi project`
- `chatpypi publisher`
- `chatpypi token`
- `chatpypi doctor`
- `chatpypi docs`

Legacy shortcuts remain available:

- `chatpypi init`
- `chatpypi build`
- `chatpypi check`
- `chatpypi upload`
- `chatpypi probe`

For manual token-based uploads, the current recommended command is:

```bash
export PYPI_API_TOKEN=...
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## CLI Contract

This template depends on `chatstyle>=0.1.0,<0.2.0` and `chatenv>=0.2.0,<0.3.0`. New commands should prefer:

- `CommandSchema` / `CommandField` for inputs.
- `add_interactive_option()` for the shared `-i/-I` switch.
- `resolve_command_inputs()` for missing args, defaults, TTY behavior, and validation.

## Layout

- `src/`: package source code
- `tests/code-tests/`: code tests and migrated historical tests
- `tests/cli-tests/`: real CLI tests, doc-first
- `tests/mock-cli-tests/`: mock/fake CLI tests, doc-first
- `docs/`: long-lived project docs built by mkdocs

## Development Notes

See `DEVELOP.md` and `AGENTS.md` before expanding the scaffold.
