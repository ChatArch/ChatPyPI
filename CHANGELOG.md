# Changelog

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

## YYYY-MM-DD

### Added

- Introduce the first public grouped CLI tree: `auth`, `profile`, `config`, `pkg`, `project`, `publisher`, `token`, `doctor`, and `docs`, while keeping legacy root aliases for `init/build/check/upload/probe`.
- Add `chatpypi auth session show|clear` and `chatpypi auth whoami` as the first local-session inspection helpers.
- Add `chatpypi pkg upload --token-env ...` / `--password-env ...` for manual token-backed uploads without exposing secrets on the command line.

### Changed

- Update README and docs index pages to reflect the merged CLI tree and manual token upload path.

### Fixed
