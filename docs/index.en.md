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
- `auth login`: log in to PyPI and write `PYPI_SESSION_TOKEN` back to the active ChatEnv PyPI profile
- `auth whoami`: verify the saved session against the account page
- `auth session show`
- `auth session clear`
- `project list`: read `/manage/projects/`
- `publisher list` / `publisher pending-list`: read `/manage/account/publishing/`
- `docs links|examples|open`

Registration, email verification, 2FA bootstrap, token create/revoke, and publisher write operations remain checkpoint-aware browser-assist flows.

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

After installation ChatPyPI registers a `pypi` / `chatpypi` config type through `chatenv.configs`, so ChatEnv can discover it:

```bash
chatenv list
chatenv test -t pypi
chatenv new -t pypi default
```

The current docs recommend splitting env setup into two categories: session
reads and manual uploads.

Minimum variables:

- `PYPI_USERNAME`: PyPI username; used by `chatpypi auth login`
- `PYPI_PASSWORD`: PyPI password; read indirectly through `--password-env`
- `PYPI_SESSION_TOKEN`: web-session token generated/refreshed by `chatpypi auth login` and stored in ChatEnv
- `PYPI_API_TOKEN`: PyPI API token; used by `chatpypi pkg upload --token-env PYPI_API_TOKEN`

Common optional variables:

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPI_TOTP_SECRET`

Template convention: `chatpypi init -t chatarch` generates `config.py` and a `chatenv.configs` entry point by default, so new packages are ChatEnv-discoverable. Pass `--without-chatenv-provider` only to opt out.

Conventions:

- `--token-env` / `--password-env` receive an env var name, not the secret
  itself;
- `PYPI_SESSION_TOKEN` should be isolated by ChatEnv profile; refresh it by rerunning `chatpypi auth login` when it expires; use `-e/--env-profile NAME` to select a named profile without activating it globally;
- the CLI prints only session summaries and does not echo raw cookies or
  tokens;
- if a `.env` file contains values with spaces, do not blindly `source` it.

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

## Local Preview

```bash
pip install -e ".[docs]"
mkdocs serve
```

Chinese version: [index.md](index.md).
