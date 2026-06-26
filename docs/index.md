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

- `chatpypi --version`：输出当前包版本
- `pkg`：包初始化、构建、校验、上传、名字探测
- `auth login`：登录 PyPI 并把 `PYPI_SESSION_TOKEN` 写回 active ChatEnv PyPI profile
- `auth whoami`：用 session 真实读取账号页确认登录态
- `auth session show`
- `auth session clear`
- `project list`：读取 `/manage/projects/`
- `publisher list` / `publisher pending-list`：读取 `/manage/account/publishing/`
- `docs links|examples|open`

注册、邮箱验证、2FA 初始化、token 创建/删除和 publisher 写操作仍按人工 checkpoint / browser-assist 边界处理。

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

ChatPyPI 安装后会通过 `chatenv.configs` 注册 `pypi` / `chatpypi` 配置类型，因此 ChatEnv 可以识别它：

```bash
chatenv list
chatenv test -t pypi
chatenv new -t pypi default
```

当前文档建议区分“会话读取”和“手动发布”两类变量。

最小变量：

- `PYPI_USERNAME`：PyPI 用户名；用于 `chatpypi auth login`
- `PYPI_PASSWORD`：PyPI 密码；只通过 `--password-env` 间接读取
- `PYPI_SESSION_TOKEN`：网页登录态 token；由 `chatpypi auth login` 生成/刷新并写回 ChatEnv
- `PYPI_API_TOKEN`：PyPI API token；用于 `chatpypi pkg upload --token-env PYPI_API_TOKEN`

常见可选变量：

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPI_TOTP_SECRET`

模板约定：`chatpypi init -t chatarch` 默认生成 `config.py` 和 `chatenv.configs` entry point，使新包能被 ChatEnv 发现；只有显式传 `--without-chatenv-provider` 才跳过。

约定：

- `--token-env` / `--password-env` 传的是“环境变量名”，不是秘密本身；
- `PYPI_SESSION_TOKEN` 应按 ChatEnv profile 隔离；过期时重新执行 `chatpypi auth login` 覆盖刷新；可用 `-e/--env-profile NAME` 指定 named profile，而不切换全局默认；
- CLI 默认只展示 session 摘要，不直接打印 cookie / token；
- `.env` 若含空格值，应避免直接 `source`。

示例：

```bash
export PYPI_USERNAME="your-pypi-user"
read -rsp "PyPI password: " PYPI_PASSWORD; echo; export PYPI_PASSWORD
read -rsp "PyPI TOTP secret: " PYPI_TOTP_SECRET; echo; export PYPI_TOTP_SECRET
read -rsp "PyPI API token: " PYPI_API_TOKEN; echo; export PYPI_API_TOKEN

chatpypi auth login --password-env PYPI_PASSWORD --totp-env PYPI_TOTP_SECRET
chatpypi auth whoami --format json
chatpypi project list --format json
chatpypi publisher list --format json
chatpypi publisher pending-list --format json
chatpypi auth session show --format json
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## 本地预览

```bash
pip install -e ".[docs]"
mkdocs serve
```

英文版见：[index.en.md](index.en.md)。
