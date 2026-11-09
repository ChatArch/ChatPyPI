# Development Guide

## CLI Rules

- Use `chatstyle>=0.2.1,<0.3.0` and `chatenv>=0.2.11,<0.3.0` as the canonical CLI interaction runtime.
- Use `add_tree_option()` for shared `--tree` / `--tree-brief` flags and `render_click_tree()` for programmatic Click-tree readback.
- Prefer `CommandSchema`, `CommandField`, `add_interactive_option()`, and `resolve_command_inputs()` for new commands.
- In commands opting into ChatStyle input resolution, missing recoverable args can auto-prompt on a TTY.
- `-i` forces prompting; `-I` disables prompting and fails fast only when required input is missing.
- Prompt defaults must match actual execution defaults.
- Sensitive values must stay masked in prompts and summaries.
- Prefer lazy imports in CLI wiring and keep implementation imports local when possible.

## Docs and Tests

- Use doc-first CLI testing.
- Put real CLI coverage under `tests/cli-tests/`.
- Put mock/fake CLI coverage under `tests/mock-cli-tests/`.
- Keep `README.md`, `docs/`, and `CHANGELOG.md` in sync with user-facing changes.

## Automation

- Keep automation small and reviewable.
- Prefer commands that can run in CI without interactive prompts.
- Ensure generated defaults are safe for local development.
