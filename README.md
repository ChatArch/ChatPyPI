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

- `chatpypi pkg`：包初始化、构建、检查、上传、探测
- `chatpypi auth`：登录、登出、session、初始化动作入口
- `chatpypi profile` / `chatpypi config`：本地配置与 profile
- `chatpypi project` / `chatpypi publisher` / `chatpypi token`：登录后管理对象
- `chatpypi doctor` / `chatpypi docs`：自检与文档入口

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
