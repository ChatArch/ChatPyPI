# ChatPyPI 文档

这里收纳 `ChatPyPI` 的长期维护文档。

## 当前接口方向

当前 `ChatPyPI` 既保留已有的包生命周期接口，也开始预留登录后 PyPI 操作树：

- `chatpypi pkg`
- `chatpypi auth`
- `chatpypi profile`
- `chatpypi config`
- `chatpypi project`
- `chatpypi publisher`
- `chatpypi token`
- `chatpypi doctor`
- `chatpypi docs`

兼容入口仍保留：

- `chatpypi init`
- `chatpypi build`
- `chatpypi check`
- `chatpypi upload`
- `chatpypi probe`

手动 token 发布当前建议命令：

```bash
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## 本地预览

```bash
pip install -e ".[docs]"
mkdocs serve
```

英文版见：[index.en.md](index.en.md)。
