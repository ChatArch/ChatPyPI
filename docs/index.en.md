# ChatPyPI Docs

Long-lived documentation for `ChatPyPI` lives here.

## Current CLI Direction

`ChatPyPI` now keeps the existing package lifecycle commands while reserving the
post-registration PyPI command tree:

- `chatpypi pkg`
- `chatpypi auth`
- `chatpypi profile`
- `chatpypi config`
- `chatpypi project`
- `chatpypi publisher`
- `chatpypi token`
- `chatpypi doctor`
- `chatpypi docs`

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

## Local Preview

```bash
pip install -e ".[docs]"
mkdocs serve
```

Chinese version: [index.md](index.md).
