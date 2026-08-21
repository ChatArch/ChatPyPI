# Changelog

## 0.2.11 - 2026-08-21

### Added

- Add `chatpypi --tree-brief` and scaffold it into generated ChatArch CLIs so command nodes and descriptions can be read without parameter signatures.

### Changed

- Move ChatPyPI and generated ChatArch CLI tree output to ChatStyle's shared `add_tree_option()` / `render_click_tree()` runtime.
- Raise the supported runtime bounds to `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.9,<0.3.0`.
- Smoke-test `--version`, `--tree`, and `--tree-brief` in ChatPyPI's CI and generated ChatArch CI workflows.

## 0.2.10 - 2026-08-12

### Fixed

- Harden ChatPyPI's own PyPI publish workflow so releases are tag-only, use OIDC without legacy token secrets, verify the tag matches `__version__`, and require the tag commit to be on `main` without fetching tags.
- Update Preview Docs workflow to fetch `gh-pages` before `mike deploy` and derive the preview URL from `mkdocs.yml` `site_url` instead of hard-coded repo URL templates.
- Enable the MkDocs Material emoji renderer baseline for ChatPyPI's docs and generated ChatArch scaffold docs.
- Update the ChatArch scaffold generator so new packages inherit the hardened publish/preview docs workflow contracts.

## 0.2.9 - 2026-08-11

### Fixed

- Require `chatenv>=0.2.7,<0.3.0` and reject invalid PyPI token profile names before token-store read/write/clear operations.
- Register a `chatenv.token_refreshers` provider so `chatenv token refresh PyPI <profile>` refreshes the PyPI web session from the matching stable ChatEnv profile instead of requiring manual token JSON.
- Scope the account-level active Publisher link fallback to the `Projects with active publishers` section so unrelated project publishing links do not count as active publishers.
- Correct the Trusted Publisher flow docs to match the live CLI: `publisher list` takes no project argument and `publisher detail` takes exactly one project argument.

## 0.2.8 - 2026-08-11

### Changed

- Move PyPI web-session runtime state from stable ChatEnv `PYPI_SESSION_TOKEN` fields into ChatEnv's generic token store at `tokens/PyPI/<profile>.json`.
- Remove `PYPI_SESSION_TOKEN` from the ChatPyPI ChatEnv provider schema; stable env profiles now keep account/config values only.
- Make `chatpypi auth login`, `auth session show|clear`, `auth whoami`, `project list`, `publisher *`, and `doctor check` use the parallel token profile selected by `-e/--env-profile`.

## 0.2.7 - 2026-08-09

### Added

- Add a top-level `chatpypi --tree` readback path that renders the registered Python package/PyPI helper CLI tree.
- Make the generated ChatArch scaffold CLI include top-level `--tree` and a default tree smoke test alongside `--help` and `--version`.

### Changed

- Align ChatPyPI's bilingual CLI tree docs and generated ChatArch template docs with the `--tree` contract.

## 0.2.6 - 2026-07-27

### Fixed

- Bound ChatArch scaffold docs dependencies so generated packages keep strict MkDocs builds stable across new MkDocs Material releases.
- Include generated `site/` docs output in scaffold `.gitignore` to avoid committing local MkDocs builds.

## 0.2.5 - 2026-07-24

### Added

- Add MkDocs Material + static i18n docs scaffolding to the ChatArch package template.
- Generate ChatArch Pages URLs and Preview Docs links from a configurable docs domain without adding repository-level domain files by default.
- Add starter docs pages for scenario index, CLI tree, capability map, and Python interface tree without a default plan page.
- Promote ChatPyPI's own `docs/cli-tree.md` into the primary annotated CLI tree entry and add an English mirror.

### Changed

- Move ChatPyPI's own documentation and README docs links to the ChatArch Pages domain.

## 0.2.3 - 2026-06-27

### Added

- Add direct active Trusted Publisher operations for existing PyPI projects:
  - `chatpypi publisher detail <project>` reads project-level publisher details.
  - `chatpypi publisher add-github <project> --owner ... --repo ... --workflow ...` adds or idempotently verifies a GitHub active publisher with readback.
- Parse project publisher pages into structured `publisher`, `repository`, `workflow`, and normalized environment fields.

### Changed

- Clarify that `pending-*` publisher commands are only for true pending registration/pre-project exceptions or stale pending cleanup. Existing PyPI project Publisher writes should go through active `add-github`, not a pending flow.

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
