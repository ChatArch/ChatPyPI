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
- `auth whoami` / `auth session show|clear`：本地 session 摘要读取
- `docs`：输出文档链接与示例命令

其余子命令目前作为保留入口，先把稳定 CLI 树固定下来。

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

当前建议把 PyPI 相关变量显式放到 shell env、`.env` 或 profile 配置里。最小集合分两类：

- 登录后读取 / session 复用：
  - `PYPI_SESSION_FILE`：本地 session JSON 文件路径
- 手动发布：
  - `PYPI_API_TOKEN`：PyPI API token，配合 `chatpypi pkg upload --token-env PYPI_API_TOKEN`

如果后续接入浏览器协作登录 / 2FA，常见可选变量包括：

- `PYPI_USERNAME`
- `PYPI_PASSWORD`
- `PYPI_TOTP_SECRET`

推荐约定：

- 不要把 token、密码直接写进命令行参数；
- `--token-env` / `--password-env` 只接收“环境变量名”，CLI 会在运行时读取其值；
- `PYPI_SESSION_FILE` 指向单个 profile 的单个 session 文件，CLI 只输出非敏感摘要，不直接回显 cookie；
- `.env` 中若有包含空格的值，不要直接 `source .env`，应使用更安全的解析方式。

示例：

```bash
export PYPI_SESSION_FILE="$HOME/.config/chatpypi/default/session.json"
export PYPI_API_TOKEN="pypi-***"

chatpypi auth session show --format json
chatpypi pkg upload --project-dir ./demo-pkg --token-env PYPI_API_TOKEN
```

## CLI 规范

这个模板默认依赖 `chatstyle>=0.1.0,<0.2.0` 和 `chatenv>=0.2.0,<0.3.0`，新的命令应优先使用：

- `CommandSchema` / `CommandField` 描述输入。
- `add_interactive_option()` 提供统一 `-i/-I`。
- `resolve_command_inputs()` 统一缺参补问、默认值、TTY 与校验。

## 目录结构

- `src/`：包源码
- `tests/code-tests/`：代码测试和历史测试迁移
- `tests/cli-tests/`：真实 CLI 测试，doc-first
- `tests/mock-cli-tests/`：mock/fake CLI 测试，doc-first
- `docs/`：长期维护文档，由 mkdocs 构建

## 开发说明

扩展脚手架前，先阅读 `DEVELOP.md` 和 `AGENTS.md`。
