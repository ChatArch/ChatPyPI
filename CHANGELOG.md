# Changelog

## 0.2.2 - 2026-06-26

### Fixed

- Start generated `chatarch` scaffold packages with a minimal CLI skeleton, version/help smoke paths, and package-owned command extension points.
- Add env-backed `PYPI_SESSION_TOKEN` as the default web-session storage path; `chatpypi auth login` refreshes it in the active or `-e/--env-profile` selected ChatEnv PyPI profile instead of maintaining a separate session file.
- Make `chatpypi auth login` perform a real PyPI login and handle TOTP when `PYPI_TOTP_SECRET` is available.
- Make `chatpypi auth whoami` validate the saved session against the PyPI account page instead of only reading local JSON.
- Make `chatpypi project list`, `chatpypi publisher list`, `chatpypi publisher pending-list`, and `chatpypi doctor check` use the saved logged-in session instead of reserved placeholder commands.
- Keep registration and high-sensitivity token/publisher write actions as checkpoint-aware assist flows rather than pretending they are fully automated.

## 0.2.1 - 2026-06-26

### Fixed

- Register ChatPyPI as a `chatenv.configs` provider so `chatenv` can discover the PyPI/ChatPyPI config schema.
- Add a `chatpypi.config.PyPIConfig` schema for `PYPI_USERNAME`, `PYPI_EMAIL`, `PYPI_NAME`, `PYPI_PASSWORD`, `PYPI_API_TOKEN`, `PYPI_TOTP_SECRET`, and session-related env keys.
- Make the `chatarch` scaffold template generate its own ChatEnv provider by default, while keeping `--without-chatenv-provider` available for opt-out.

## 0.2.0 - 2026-06-26

### Added

- Introduce the first public grouped CLI tree: `auth`, `profile`, `config`, `pkg`, `project`, `publisher`, `token`, `doctor`, and `docs`, while keeping legacy root aliases for `init/build/check/upload/probe`.
- Add `chatpypi auth session show|clear` and `chatpypi auth whoami` as the first local-session inspection helpers.
- Add `chatpypi pkg upload --token-env ...` / `--password-env ...` for manual token-backed uploads without exposing secrets on the command line.
- Add generated `chatarch` template support for `--version` on the scaffolded CLI.

### Changed

- Update README and docs index pages to reflect the merged CLI tree and manual token upload path.
- Document the full reserved CLI tree plus the current env configuration for session-backed reads and manual token uploads.
- Make reserved operational commands fail non-zero until their real implementations land.

### Fixed

- Add a top-level `chatpypi --version` release-gate smoke path.
- Validate local session JSON shapes instead of crashing on malformed data.
- Redact token/password environment values from upload subprocess output before echoing it.
- Preserve two-argument `upload_distributions(..., runner=...)` compatibility when no env override is provided.
- Add CLI coverage for `PYPI_SESSION_TOKEN` reads and clearer failure behavior when a required secret env var is unset.

## 0.1.4 - 2026-06-25

### Fixed

- Make `chatpypi build/check/upload` independent in clean installs by adding bounded runtime dependencies on `build` and `twine`.
- Add package-operation logging for build/check/upload while keeping default CLI output stable.
- Update stale `chattool pypi build` error text to `chatpypi build`.

## 0.1.3 - 2026-06-25

### Fixed

- Fix generated `chatarch` publish workflow to match ChatArch Trusted Publisher defaults: no default `environment: pypi`, workflow-level `contents: read`, job-level `id-token: write`.

## 0.1.2 - 2026-06-25

### Fixed

- Align publish workflow with ChatArch Trusted Publisher configuration by removing the GitHub environment claim.

## 0.1.1 - 2026-06-25

### Added

- Extract ChatTool PyPI helpers into the standalone ChatPyPI package.
- Expose importable Python APIs for scaffold/build/check/probe/upload helpers.
- Provide `chatpypi` CLI as a thin adapter over the package API.
