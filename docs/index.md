# ChatPyPI 文档

这里收纳 `ChatPyPI` 的长期维护文档。

## 当前接口方向

当前 `ChatPyPI` 既保留已有的包生命周期接口，也开始预留登录后 PyPI 操作树：

```text
chatpypi
├── auth
│   ├── login / logout / whoami
│   ├── register / verify-email / setup-2fa / recovery-codes
│   └── session
│       ├── show / export / import / clear
├── profile
│   ├── list / show / use / create / delete
├── config
│   ├── list / get / set / unset
├── pkg
│   ├── init / build / check / upload / probe
├── project
│   ├── list / show
├── publisher
│   ├── list / pending-list / pending-add / pending-remove
├── token
│   ├── list / create / revoke
├── doctor
│   └── check
└── docs
    ├── links / examples / open
```

当前真正已落地的主路径：

- `pkg`：包初始化、构建、校验、上传、名字探测
- `auth whoami`
- `auth session show`
- `auth session clear`
- `docs links|examples|open`

其余命令现在先保留接口位置，后续逐步接入真实 PyPI / 浏览器协作流程。

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

## Env 配置说明

当前文档建议区分“会话读取”和“手动发布”两类变量。

最小变量：

- `PYPI_SESSION_FILE`：本地 session JSON 文件路径；用于 `chatpypi auth whoami`、`chatpypi auth session show|clear`
- `PYPI_API_TOKEN`：PyPI API token；用于 `chatpypi pkg upload --token-env PYPI_API_TOKEN`

常见可选变量：

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPI_TOTP_SECRET`

约定：

- `--token-env` / `--password-env` 传的是“环境变量名”，不是秘密本身；
- session 文件应按 profile 隔离，通常一个 profile 一个 `PYPI_SESSION_FILE`；
- CLI 默认只展示 session 摘要，不直接打印 cookie / token；
- `.env` 若含空格值，应避免直接 `source`。

示例：

```bash
export PYPI_SESSION_FILE="$HOME/.config/chatpypi/default/session.json"
export PYPI_API_TOKEN="pypi-***"

chatpypi auth session show --format json
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## 本地预览

```bash
pip install -e ".[docs]"
mkdocs serve
```

英文版见：[index.en.md](index.en.md)。
