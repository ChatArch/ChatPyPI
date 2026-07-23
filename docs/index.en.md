# ChatPyPI Docs

ChatPyPI is ChatArch's Python package lifecycle and PyPI automation CLI. It covers package scaffold generation, build/check/upload workflows, PyPI session handling, project reads, and Trusted Publisher helpers.

## Choose Documentation by Scenario

| Scenario | Document | Status |
| --- | --- | --- |
| See the supported ChatPyPI command surface at a glance | [CLI Tree](cli-tree.md) | Documented as the primary command entry |
| Create a ChatArch Python package template with MkDocs, i18n, and Actions | [ChatArch Template and Docs Flow](template-flow.md) | Implemented; this PR updates the template contract |
| Build, check, upload Python packages, or configure Trusted Publishers | [Publishing and Trusted Publisher Flow](pypi-flow.md) | Partially implemented; some flows remain human-checkpointed |
| Review Python interfaces behind commands | [Python Interface Tree](interface-tree.md) | Documented |

## Primary Entry Points

<div class="grid cards" markdown>

- **CLI Tree**

    The primary command-surface entry. Start here to decide whether you need package lifecycle, session, Publisher, token, or docs commands.

    [Open CLI Tree](cli-tree.md)

- **Template Flow**

    Review what `chatpypi init -t chatarch` generates for docs slots and workflows.

    [Open Template Flow](template-flow.md)

- **Publishing Flow**

    Follow build, check, upload, Trusted Publisher, and session-backed operation paths.

    [Open Publishing Flow](pypi-flow.md)

- **Python Interface Tree**

    Trace importable functions and service layers behind commands so logic does not live only in CLI callbacks.

    [Open Interface Tree](interface-tree.md)

</div>

## Document Organization

This site follows the ChatArch docs convention:

- **CLI Tree**: command tree, status, command groups, and checkpoint boundaries.
- **Template Creation**: what ChatPyPI should generate as a package scaffold.
- **PyPI Publishing**: package lifecycle, login/session, project, and Trusted Publisher flows.
- **Commands and APIs**: command tree, Python API mapping, and thin CLI constraints.

## Status Contract

- **Implemented**: code, tests, or command routes exist.
- **Verified**: covered by unit tests, CI, local smoke, or real PyPI/Pages practice.
- **Planned / checkpoint**: keep boundary and safety notes only; turn into operation docs after implementation and validation.

## Main Commands

```bash
chatpypi --version
chatpypi --help
chatpypi pkg --help
chatpypi auth --help
chatpypi publisher --help
```
