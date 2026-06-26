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

```text
chatpypi
├── auth
│   ├── login
│   ├── logout
│   ├── whoami
│   ├── register
│   ├── verify-email
│   ├── setup-2fa
│   ├── recovery-codes
│   └── session
│       ├── show
│       ├── export
│       ├── import
│       └── clear
├── profile
│   ├── list
│   ├── show
│   ├── use
│   ├── create
│   └── delete
├── config
│   ├── list
│   ├── get
│   ├── set
│   └── unset
├── pkg
│   ├── init
│   ├── build
│   ├── check
│   ├── upload
│   └── probe
├── project
│   ├── list
│   └── show
├── publisher
│   ├── list
│   ├── pending-list
│   ├── pending-add
│   └── pending-remove
├── token
│   ├── list
│   ├── create
│   └── revoke
├── doctor
│   └── check
└── docs
    ├── links
    ├── examples
    └── open
```

Current implementation focus:

- `pkg`: package init/build/check/upload/probe
- `auth whoami` / `auth session show|clear`: local session summary helpers
- `docs`: documentation links and example commands

The remaining subcommands are reserved entry points so the public tree can stay
stable while the deeper workflows land.

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

## Env Configuration

PyPI-related values should live in shell env, `.env`, or a local profile file.
The minimum set currently falls into two categories:

- Session-backed read flows:
  - `PYPI_SESSION_FILE`: path to the local session JSON file
- Manual uploads:
  - `PYPI_API_TOKEN`: PyPI API token used with `chatpypi pkg upload --token-env PYPI_API_TOKEN`

If you later connect browser-assisted login or 2FA bootstrap, the common
optional variables are:

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPI_TOTP_SECRET`

Recommended rules:

- do not pass tokens or passwords directly on the command line;
- `--token-env` / `--password-env` accept an env var name, and the CLI resolves
  the secret value at runtime;
- `PYPI_SESSION_FILE` should point to one session file for one local profile,
  and the CLI only prints non-sensitive summaries instead of raw cookies;
- if a `.env` file contains values with spaces, avoid blindly running
  `source .env`; parse it safely instead.

Example:

```bash
export PYPI_SESSION_FILE="$HOME/.config/chatpypi/default/session.json"
export PYPI_API_TOKEN="pypi-***"

chatpypi auth session show --format json
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
