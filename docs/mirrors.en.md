# uv / pip User Download Indexes

`chatpypi mirror` manages only the **current user's** default uv and pip download indexes. It is independent of ChatUp aliases, PyPI login, Publishers, upload repositories, `.pypirc`, proxies, and shell configuration.

## Commands

```bash
chatpypi mirror show [--tool uv|pip|all] [--format text|json]
chatpypi mirror set [default|tsinghua] [--tool uv|pip|all] [--dry-run] [-i|-I] [--format text|json]
```

`--tool` defaults to `all`. `default` writes `https://pypi.org/simple`; `tsinghua` writes `https://pypi.tuna.tsinghua.edu.cn/simple`. A missing preset prompts through ChatStyle only when prompting is allowed and a TTY is available; `-I` is always deterministic and fails fast. `--dry-run` is recommended first and creates no files or directories.

```bash
chatpypi mirror show
chatpypi mirror set tsinghua --dry-run
chatpypi mirror set tsinghua -I --format json
chatpypi mirror set default --tool pip -I
```

## Native User Files

ChatPyPI writes configuration read by the tools themselves; it does not keep a private mirror store:

| Tool / platform | Current-user target |
| --- | --- |
| uv, Linux / macOS | `$XDG_CONFIG_HOME/uv/uv.toml`, falling back to `~/.config/uv/uv.toml` |
| uv, Windows | `%APPDATA%\\uv\\uv.toml` |
| pip, Linux | `$XDG_CONFIG_HOME/pip/pip.conf`, falling back to `~/.config/pip/pip.conf` |
| pip, macOS | pip's native existing-directory rule for `$XDG_DATA_HOME/pip` or `~/Library/Application Support/pip`, otherwise `~/.config/pip/pip.conf` |
| pip, Windows | `%APPDATA%\\pip\\pip.ini` |

uv uses modern `[[index]]`, `url`, and `default = true` entries. `tomlkit` preserves unrelated options, comments, and indexes. Known official/Tsinghua `index-url`, `default-index`, or `[pip].index-url` values are migrated safely. A custom legacy value, custom default index, retargeted named default index, or multiple default indexes is rejected before any write so private authentication and index priority are not silently reassigned.

pip changes only `[global] index-url` in the current file and preserves other sections and options. A standard INI parser handles colon delimiters, underscore aliases, and old multiline values; rewriting may normalize formatting and comments. The legacy user file is still read and validated; pip's current user file overrides its legacy value. The command does not change system/site (including active-venv) configuration or command-specific sections, which may still override the user default.

## Status and Safety Boundary

`show` explicitly reports `USER configuration`; it does not claim to show global or ultimately effective configuration. Unknown/custom URLs are always rendered as `custom / REDACTED`. When relevant environment variables exist, only their names are reported:

- uv: `UV_DEFAULT_INDEX`, `UV_INDEX_URL`, `UV_CONFIG_FILE`, `UV_INDEX`, `UV_EXTRA_INDEX_URL`
- pip: `PIP_INDEX_URL`, `PIP_CONFIG_FILE`, `PIP_EXTRA_INDEX_URL`

Environment variables, command-line arguments, uv project configuration, and pip site/command-specific configuration can still override user files. ChatPyPI does not clear the environment or claim that a subprocess can change its parent shell.

All requested configuration is parsed before writes. Target leaf symlinks are refused. Writes use private same-directory temporary files and atomic replace while preserving an existing file's mode. If the second `--tool all` target fails, the first is rolled back; a rollback failure produces an explicit fixed error. Errors and status never include an original custom URL.

## Python API

```python
from chatpypi.mirror_ops import resolve_user_config_paths, set_mirrors, show_mirrors

paths = resolve_user_config_paths()
preview = set_mirrors("tsinghua", tool="all", dry_run=True)
status = show_mirrors(tool="all")
```

`resolve_user_config_paths()`, `set_mirrors()`, and `show_mirrors()` accept injected `home`, `platform`, `env`, and explicit paths for isolated validation without touching developer configuration.
