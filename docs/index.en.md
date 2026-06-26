# ChatPyPI Docs

Long-lived documentation for `ChatPyPI` lives here.

## Current CLI Direction

`ChatPyPI` now keeps the existing package lifecycle commands while reserving the
post-registration PyPI command tree:

```text
chatpypi
├── auth
│   ├── login / logout / whoami
│   ├── register / verify-email / setup-2fa / recovery-codes
│   └── session
│       ├── show / export / import / clear
├── profile
│   ├── list / show / use / create / delete
├── config
│   ├── list / get / set / unset
├── pkg
│   ├── init / build / check / upload / probe
├── project
│   ├── list / show
├── publisher
│   ├── list / pending-list / pending-add / pending-remove
├── token
│   ├── list / create / revoke
├── doctor
│   └── check
└── docs
    ├── links / examples / open
```

Current implemented path:

- `chatpypi --version`: print the current package version
- `pkg`: package init, build, check, upload, and name probe
- `auth whoami`
- `auth session show`
- `auth session clear`
- `docs links|examples|open`

The remaining commands are reserved so the public CLI tree can stabilize before
the full browser-backed PyPI workflows land.

Legacy shortcuts remain available:

- `chatpypi init`
- `chatpypi build`
- `chatpypi check`
- `chatpypi upload`
- `chatpypi probe`

For manual token-based uploads, the current recommended command is:

```bash
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## Env Configuration

The current docs recommend splitting env setup into two categories: session
reads and manual uploads.

Minimum variables:

- `PYPI_SESSION_FILE`: path to a local session JSON file; used by `chatpypi auth whoami` and `chatpypi auth session show|clear`
- `PYPI_API_TOKEN`: PyPI API token; used by `chatpypi pkg upload --token-env PYPI_API_TOKEN`

Common optional variables:

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPI_TOTP_SECRET`

Conventions:

- `--token-env` / `--password-env` receive an env var name, not the secret
  itself;
- session files should be isolated by profile, usually one
  `PYPI_SESSION_FILE` per local profile;
- the CLI prints only session summaries and does not echo raw cookies or
  tokens;
- if a `.env` file contains values with spaces, do not blindly `source` it.

Example:

```bash
export PYPI_SESSION_FILE="$HOME/.config/chatpypi/default/session.json"
export PYPI_API_TOKEN="pypi-***"

chatpypi auth session show --format json
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## Local Preview

```bash
pip install -e ".[docs]"
mkdocs serve
```

Chinese version: [index.md](index.md).
