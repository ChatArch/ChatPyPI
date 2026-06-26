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
chatpypi --version
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
- `auth login`: log in to PyPI with username/password and optional TOTP, then refresh `PYPI_SESSION_TOKEN` in the active ChatEnv PyPI profile
- `auth whoami` / `auth session show|clear`: validate the saved session and show non-sensitive local summaries
- `project list`: read the logged-in account's PyPI projects page
- `publisher list` / `publisher pending-list`: read the logged-in account's Publishing page
- `docs`: documentation links and example commands

Registration, email verification, 2FA bootstrap, token create/revoke, and publisher write operations remain checkpoint-aware browser-assist flows instead of unconditional headless automation.

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

ChatPyPI registers a `pypi` / `chatpypi` config type through `chatenv.configs`, so ChatEnv can discover and manage it after installation:

```bash
chatenv list
chatenv test -t pypi
chatenv new -t pypi default
```

PyPI-related values should live in a ChatEnv profile, shell env, `.env`, or a local profile file.
The minimum set currently falls into two categories:

- Session-backed read flows:
  - `PYPI_USERNAME`: PyPI username for `chatpypi auth login`
  - `PYPI_PASSWORD`: PyPI password, read indirectly through `--password-env`
  - `PYPI_TOTP_SECRET`: optional TOTP secret for 2FA checkpoints
  - `PYPI_SESSION_TOKEN`: web-session token generated/refreshed by `chatpypi auth login` and stored in ChatEnv
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
- `PYPI_SESSION_TOKEN` is sensitive and is written back to the active ChatEnv PyPI profile by `chatpypi auth login`; use `-e/--env-profile NAME` to read or write a named profile without activating it globally; the CLI only prints non-sensitive summaries instead of raw cookies;
- if a `.env` file contains values with spaces, avoid blindly running
  `source .env`; parse it safely instead.

Example:

```bash
export PYPI_USERNAME="your-pypi-user"
read -rsp "PyPI password: " PYPI_PASSWORD; echo; export PYPI_PASSWORD
read -rsp "PyPI TOTP secret: " PYPI_TOTP_SECRET; echo; export PYPI_TOTP_SECRET
read -rsp "PyPI API token: " PYPI_API_TOKEN; echo; export PYPI_API_TOKEN

chatpypi auth login --password-env PYPI_PASSWORD --totp-env PYPI_TOTP_SECRET
chatpypi auth whoami --format json
chatpypi project list --format json
chatpypi publisher list --format json
chatpypi publisher pending-list --format json
chatpypi auth session show --format json
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## CLI Contract

This template depends on `chatstyle>=0.1.0,<0.2.0` and `chatenv>=0.2.0,<0.3.0`. New commands should prefer:

- `CommandSchema` / `CommandField` for inputs.
- `add_interactive_option()` for the shared `-i/-I` switch.
- `resolve_command_inputs()` for missing args, defaults, TTY behavior, and validation.
- `chatpypi init -t chatarch` generates `config.py` and a `chatenv.configs` entry point by default; pass `--without-chatenv-provider` only when the package should not be ChatEnv-discoverable.

## Layout

- `src/`: package source code
- `tests/code-tests/`: code tests and migrated historical tests
- `tests/cli-tests/`: real CLI tests, doc-first
- `tests/mock-cli-tests/`: mock/fake CLI tests, doc-first
- `docs/`: long-lived project docs built by mkdocs

## Development Notes

See `DEVELOP.md` and `AGENTS.md` before expanding the scaffold.
