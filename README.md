<div align="center">
    <a href="https://pypi.python.org/pypi/ChatPyPI">
        <img src="https://img.shields.io/pypi/v/ChatPyPI.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/ChatPyPI/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/ChatPyPI/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
    <a href="https://arch.gh.wzhecnu.cn/ChatPyPI/">
        <img src="https://img.shields.io/badge/docs-mkdocs-blue.svg" alt="Documentation" />
    </a>
</div>

<div align="center">

[英文版](README.en.md) | [简体中文](README.md)
</div>

# ChatPyPI

ChatPyPI: ChatArch Python package lifecycle helper extracted from ChatTool.

## 快速开始

```bash
pip install -e ".[dev]"
chatpypi --help
chatpypi --version
chatpypi --tree
chatpypi --tree-brief
chatpypi pkg init demo-pkg
python -m pytest -q
python -m build
```

## 当前命令树

`ChatPyPI` 正在从单纯的包生命周期工具，扩展为“包 + 登录后 PyPI 操作”工具。当前公共树结构已经预留：

`chatpypi --tree` 使用 ChatStyle 共享运行时输出带参数签名的注册树；`chatpypi --tree-brief` 保留命令节点和描述，但省略参数签名。

完整带注释的命令树见文档站： https://arch.gh.wzhecnu.cn/ChatPyPI/cli-tree/

```text
chatpypi
├── --help
├── --version
├── --tree
├── --tree-brief
├── auth
│   ├── login
│   ├── logout
│   ├── whoami
│   ├── register
│   ├── verify-email
│   ├── setup-2fa
│   ├── recovery-codes
│   └── session
│       ├── show
│       ├── export
│       ├── import
│       └── clear
├── profile
│   ├── list
│   ├── show
│   ├── use
│   ├── create
│   └── delete
├── config
│   ├── list
│   ├── get
│   ├── set
│   └── unset
├── mirror
│   ├── show
│   └── set
├── pkg
│   ├── init
│   ├── build
│   ├── check
│   ├── upload
│   └── probe
├── project
│   ├── list
│   └── show
├── publisher
│   ├── list
│   ├── detail
│   ├── add-github
│   ├── pending-list
│   ├── pending-add
│   └── pending-remove
├── token
│   ├── list
│   ├── create
│   └── revoke
├── doctor
│   └── check
└── docs
    ├── links
    ├── examples
    └── open
```

当前实现重点：

- `mirror show|set`：查看或持久切换当前用户 uv / pip 原生默认下载源（official/Tsinghua），支持 dry-run、JSON、环境覆盖提示和安全 transaction
- `pkg`：包初始化、构建、检查、上传、探测
- `auth login`：使用用户名、密码和可选 TOTP 获取真实 PyPI 登录 session；可显式等待一次邮件确认链接，最终核验实际账号后再写入 ChatEnv token profile
- `auth whoami` / `auth session show|clear`：真实 session 验证与本地 session 摘要读取
- `project list`：读取登录账号的 PyPI projects 页面
- `publisher list` / `publisher detail`：读取账号级和项目级 Trusted Publisher 状态
- `publisher add-github`：对已存在 PyPI project 直接添加/幂等确认 GitHub active Trusted Publisher，并做读回校验
- `publisher pending-list` / `pending-add` / `pending-remove`：仅用于真正 pending 的注册/占位前例外流程或清理 stale pending；不是普通 Publisher 默认路径
- `docs`：输出文档链接与示例命令

登录中新设备触发的邮件确认 checkpoint 已支持显式等待；账号注册、邮箱地址验证、2FA 初始化、token 创建/删除等需要人工验证、二维码或复杂 checkpoint 的流程仍按 checkpoint / browser-assist 边界处理。已存在 PyPI project 的 Publisher 写操作不应 pending：应直接用 `publisher add-github` 完成并读回确认。

旧命令仍兼容：

- `chatpypi init`
- `chatpypi build`
- `chatpypi check`
- `chatpypi upload`
- `chatpypi probe`

手动 token 发布当前可直接走：

```bash
export PYPI_API_TOKEN=...
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## Env 配置

ChatPyPI 会通过 `chatenv.configs` 注册 `pypi` / `chatpypi` 配置类型，因此安装后可被 ChatEnv 发现和管理：

```bash
chatenv list
chatenv test -t pypi
chatenv new -t pypi default
```

当前建议把 PyPI 相关变量显式放到 ChatEnv profile、shell env、`.env` 或 profile 配置里。最小集合分两类：

- 登录后读取 / session 复用：
  - `PYPI_USERNAME`：PyPI 用户名，用于 `chatpypi auth login`
  - `PYPI_PASSWORD`：PyPI 密码，只通过 `--password-env` 或 matching ChatEnv refresh provider 读取，不直接作为命令行值传入
  - `PYPI_TOTP_SECRET`：可选 TOTP secret，用于自动完成 2FA checkpoint
  - `PYPI_PROXY_URL`：可选的 PyPI 网页登录/管理专用 HTTP(S) 代理，优先采用所选 profile 配置并覆盖该请求的 `NO_PROXY`；profile 使用该项时也必须包含同账号的 `PYPI_USERNAME`，不修改全局代理或下载镜像。
  - Web 登录态 session：`chatpypi auth login` 或 `chatenv token refresh PyPI <profile>` 生成/刷新到 `tokens/PyPI/<profile>.json`，与 `envs/PyPI/<profile>.env` 一一对应
- 手动发布：
  - `PYPI_API_TOKEN`：PyPI API token，配合 `chatpypi pkg upload --token-env PYPI_API_TOKEN`

如果后续接入浏览器协作登录 / 2FA，常见可选变量包括：

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPI_TOTP_SECRET`

推荐约定：

- 不要把 token、密码直接写进命令行参数；
- `--token-env` / `--password-env` 只接收“环境变量名”，CLI 会在运行时读取其值；
- Web session 属于动态 runtime state，由 `chatpypi auth login` 默认写回 ChatEnv token profile；可以用 `-e/--env-profile NAME` 指定读取/写入同名 token profile，而不切换全局默认；CLI 只输出非敏感摘要，不直接回显 cookie；
- 新设备要求邮件确认时，显式使用 `--wait-email --wait-timeout 600`。CLI 只接受当前官方 PyPI origin 的 HTTPS `/account/confirm-login/?token=...` 链接，并用隐藏输入读取；它不会自动读取邮箱、轮询、重登录或重发邮件。非 TTY 或不支持安全 POSIX timer 的环境应使用 Python callback API；
- `.env` 中若有包含空格的值，不要直接 `source .env`，应使用更安全的解析方式。

示例：

```bash
export PYPI_USERNAME="your-pypi-user"
read -rsp "PyPI password: " PYPI_PASSWORD; echo; export PYPI_PASSWORD
read -rsp "PyPI TOTP secret: " PYPI_TOTP_SECRET; echo; export PYPI_TOTP_SECRET  # optional; needed when 2FA is enabled
read -rsp "PyPI API token: " PYPI_API_TOKEN; echo; export PYPI_API_TOKEN

chatpypi auth login --password-env PYPI_PASSWORD --totp-env PYPI_TOTP_SECRET
chatpypi mirror set tsinghua --dry-run
chatpypi mirror show --format json
chatpypi auth login -e PROFILE --wait-email --wait-timeout 600
chatpypi auth whoami --format json
chatpypi project list --format json
chatpypi publisher list --format json
chatpypi publisher pending-list --format json
chatpypi auth session show --format json
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

自动化可调用 `chatpypi.session_ops.login_to_pypi(..., confirmation_provider=callback, confirmation_timeout=600)`。callback 接收安全的 `EmailConfirmationCheckpoint` 和剩余秒数，并返回完整确认链接。任意第三方 Python callback 必须自行遵守 deadline；API 会在调用前后检查过期，但不承诺强制中断任意 Python 代码。失败、超时、取消、无效链接或账号不匹配时不会由 CLI 写入 token store。

## 命令行规范

这个模板默认依赖 `chatstyle>=0.2.0,<0.3.0` 和 `chatenv>=0.2.11,<0.3.0`，新增命令应优先使用：

- `add_tree_option()` 提供共享的 `--tree` / `--tree-brief`，`render_click_tree()` 从已注册 Click 元数据生成命令树。
- `CommandSchema` / `CommandField` 描述输入。
- `add_interactive_option()` 提供统一 `-i/-I`。
- `resolve_command_inputs()` 统一缺参补问、默认值、TTY 与校验。
- `chatpypi init -t chatarch` 默认生成 `config.py` 和 `chatenv.configs` 入口点；只有明确传 `--without-chatenv-provider` 时才跳过。

## 目录结构

- `src/`：包源码
- `tests/code-tests/`：代码测试和历史测试迁移
- `tests/cli-tests/`：真实 CLI 测试，doc-first
- `tests/mock-cli-tests/`：mock/fake CLI 测试，doc-first
- `docs/`：长期维护文档，由 mkdocs 构建

## 开发说明

扩展脚手架前，先阅读 `DEVELOP.md` 和 `AGENTS.md`。
