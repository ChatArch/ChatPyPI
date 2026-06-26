<div align="center">
    <a href="https://pypi.python.org/pypi/ChatPyPI">
        <img src="https://img.shields.io/pypi/v/ChatPyPI.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/ChatPyPI/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/ChatPyPI/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
    <a href="https://ChatArch.github.io/ChatPyPI">
        <img src="https://img.shields.io/badge/docs-mkdocs-blue.svg" alt="Documentation" />
    </a>
</div>

<div align="center">

[English](README.en.md) | [简体中文](README.md)
</div>

# ChatPyPI

ChatPyPI: ChatArch Python package lifecycle helper extracted from ChatTool.

## 快速开始

```bash
pip install -e ".[dev]"
chatpypi --help
chatpypi --version
chatpypi pkg init demo-pkg
python -m pytest -q
python -m build
```

## 当前 CLI 树

`ChatPyPI` 正在从单纯的包生命周期工具，扩展为“包 + 登录后 PyPI 操作”工具。当前公共树结构已经预留：

```text
chatpypi
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

- `pkg`：包初始化、构建、检查、上传、探测
- `auth login`：使用用户名、密码和可选 TOTP 获取真实 PyPI 登录 session，并写入本地 session token
- `auth whoami` / `auth session show|clear`：真实 session 验证与本地 session 摘要读取
- `project list`：读取登录账号的 PyPI projects 页面
- `publisher list` / `publisher pending-list`：读取登录账号的 Publishing 页面
- `docs`：输出文档链接与示例命令

注册、邮箱验证、2FA 初始化、token 创建/删除和 publisher 写操作仍按人工 checkpoint / browser-assist 边界处理，不把它们伪装成无条件全自动能力。

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
  - `PYPI_PASSWORD`：PyPI 密码，只通过 `--password-env` 读取，不直接作为命令行值传入
  - `PYPI_TOTP_SECRET`：可选 TOTP secret，用于自动完成 2FA checkpoint
  - `PYPI_SESSION_TOKEN`：`chatpypi auth login` 生成/刷新并写回 ChatEnv 的网页登录态 token
- 手动发布：
  - `PYPI_API_TOKEN`：PyPI API token，配合 `chatpypi pkg upload --token-env PYPI_API_TOKEN`

如果后续接入浏览器协作登录 / 2FA，常见可选变量包括：

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPI_TOTP_SECRET`

推荐约定：

- 不要把 token、密码直接写进命令行参数；
- `--token-env` / `--password-env` 只接收“环境变量名”，CLI 会在运行时读取其值；
- `PYPI_SESSION_TOKEN` 属于敏感值，由 `chatpypi auth login` 默认写回 active ChatEnv PyPI profile；也可以用 `-e/--env-profile NAME` 指定读取/写入某个 named profile，而不切换全局默认；CLI 只输出非敏感摘要，不直接回显 cookie；
- `.env` 中若有包含空格的值，不要直接 `source .env`，应使用更安全的解析方式。

示例：

```bash
export PYPI_USERNAME="your-pypi-user"
read -rsp "PyPI password: " PYPI_PASSWORD; echo; export PYPI_PASSWORD
read -rsp "PyPI TOTP secret: " PYPI_TOTP_SECRET; echo; export PYPI_TOTP_SECRET  # optional; needed when 2FA is enabled
read -rsp "PyPI API token: " PYPI_API_TOKEN; echo; export PYPI_API_TOKEN

chatpypi auth login --password-env PYPI_PASSWORD --totp-env PYPI_TOTP_SECRET
chatpypi auth whoami --format json
chatpypi project list --format json
chatpypi publisher list --format json
chatpypi publisher pending-list --format json
chatpypi auth session show --format json
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## CLI 规范

这个模板默认依赖 `chatstyle>=0.1.0,<0.2.0` 和 `chatenv>=0.2.0,<0.3.0`，新的命令应优先使用：

- `CommandSchema` / `CommandField` 描述输入。
- `add_interactive_option()` 提供统一 `-i/-I`。
- `resolve_command_inputs()` 统一缺参补问、默认值、TTY 与校验。
- `chatpypi init -t chatarch` 默认生成 `config.py` 和 `chatenv.configs` entry point；只有明确传 `--without-chatenv-provider` 时才跳过。

## 目录结构

- `src/`：包源码
- `tests/code-tests/`：代码测试和历史测试迁移
- `tests/cli-tests/`：真实 CLI 测试，doc-first
- `tests/mock-cli-tests/`：mock/fake CLI 测试，doc-first
- `docs/`：长期维护文档，由 mkdocs 构建

## 开发说明

扩展脚手架前，先阅读 `DEVELOP.md` 和 `AGENTS.md`。
