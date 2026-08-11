# 发布与 Trusted Publisher Flow

这个页面记录 ChatPyPI 当前 PyPI 发布相关 Flow。已实现和未实现能力必须分开描述。

## 已实现：包生命周期

```bash
chatpypi init my-package
chatpypi pkg build --project-dir ./my-package
chatpypi pkg check --project-dir ./my-package
chatpypi pkg upload --project-dir ./my-package --token-env PYPI_API_TOKEN
```

说明：

- `init` 创建 src-layout Python 包。
- `build` 调用 Python build 工具生成 wheel/sdist。
- `check` 调用 twine check。
- `upload` 支持通过环境变量传递 PyPI API token，不把 token 写入命令行参数。

## 已实现：登录态和项目读取

```bash
chatpypi auth login --username <user> --password-env PYPI_PASSWORD
chatpypi auth whoami
chatpypi auth session show
chatpypi project list
```

登录态通过 ChatEnv token store 的 `tokens/PyPI/<profile>.json` 管理，并与 ChatEnv `pypi` env profile 一一对应。报告和日志中不得输出 session token、cookie 或密码。

## 已实现：Trusted Publisher 辅助

```bash
chatpypi publisher list <project>
chatpypi publisher detail <project> <publisher-id>
chatpypi publisher add-github <project> --owner <owner> --repo <repo> --workflow publish.yml
```

当前重点是给已有 PyPI project 配置 active Trusted Publisher。`pending-*` 只用于新项目注册前 pending 例外或 stale pending 清理。

## 未实现或 checkpoint Flow

以下能力不要写成完全自动化教程：

- PyPI 账号注册。
- 邮箱验证。
- 2FA 初始化和 recovery codes。
- token 创建/删除。
- 需要浏览器、人机验证、二维码或复杂 checkpoint 的流程。

这些能力后续应按 browser-assist / checkpoint 设计，再补真实实践文档。
