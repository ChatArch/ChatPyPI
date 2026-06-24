# Changelog

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

### Changed

### Fixed
