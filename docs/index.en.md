# ChatPyPI Docs

ChatPyPI is ChatArch's Python package lifecycle and PyPI automation CLI/API package. It covers package scaffold generation, build/check/upload workflows, PyPI session handling, project reads, and Trusted Publisher helpers.

## Choose By Scenario

| Scenario | Document | Status |
| --- | --- | --- |
| Create a ChatArch Python package template with MkDocs, i18n, and Actions | [ChatArch Template and Docs Flow](template-flow.md) | Implemented; this PR updates the template contract |
| Build, check, upload Python packages, or configure Trusted Publishers | [Publishing and Trusted Publisher Flow](pypi-flow.md) | Partially implemented; some flows remain human-checkpointed |
| Review the current command tree and not-implemented boundaries | [CLI Capability Map](cli-tree.md) | Documented |
| Review Python interfaces behind the CLI | [Python Interface Tree](interface-tree.md) | Documented |
| Maintain roadmap and review contracts | [Development Plan](development-plan.md) | Documented |

## Documentation Organization

This site follows the ChatArch docs convention:

- **Template Creation**: what ChatPyPI should generate as a package scaffold.
- **PyPI Publishing**: package lifecycle, login/session, project, and Trusted Publisher flows.
- **Commands and APIs**: command tree, Python API mapping, and thin CLI constraints.
- **Roadmap**: planned-only capabilities and safety requirements.

## Status Legend

- **Implemented**: code, tests, or CLI routes exist.
- **Verified**: covered by unit tests, CI, local smoke, or real PyPI/Pages practice.
- **Not implemented**: keep as roadmap and safety notes only; turn into operation docs after implementation and validation.

## Main Commands

```bash
chatpypi --version
chatpypi init --help
chatpypi pkg --help
chatpypi auth --help
chatpypi publisher --help
```

## Local Preview

```bash
python -m pip install -e ".[docs]"
mkdocs serve
```

Chinese home page: https://arch.gh.wzhecnu.cn/ChatPyPI/.
