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
chatpypi auth login -e PROFILE --wait-email --wait-timeout 600
chatenv token refresh PyPI <profile>
chatpypi auth whoami
chatpypi auth session show
chatpypi project list
```

登录态通过 ChatEnv token store 的 `tokens/PyPI/<profile>.json` 管理，并与 ChatEnv `pypi` env profile 一一对应。`chatpypi auth login` 是 ChatPyPI 原生命令；安装 ChatPyPI 后也会注册 `chatenv.token_refreshers`，因此 `chatenv token refresh PyPI <profile>` 会调用 ChatPyPI 的 PyPI 登录逻辑，从 matching stable profile 读取 `PYPI_USERNAME`、`PYPI_PASSWORD` 和可选 `PYPI_TOTP_SECRET` 后刷新 runtime session。报告和日志中不得输出 session token、cookie、密码或邮件确认链接。

`--wait-email` 只处理登录过程中 PyPI `/account/confirm-login/` 新设备检查点，确认值是邮件中的完整链接而不是数字 OTP。它等待一次，不轮询、不重试登录、不重发邮件，并只允许 `pypi.org` 或 `test.pypi.org` 当前 origin 的严格 HTTPS 链接。确认请求复用登录 Session；成功跳转不携带 token Referer，随后从 account 页面读取实际用户名并与请求用户名精确匹配。只有全部成功后 CLI 才写入所选 token profile。未启用 wait 会返回明确的 confirmation-required 错误。

终端模式使用 ChatStyle 隐藏输入和 POSIX 主线程 timer；非 TTY、已有调用方 alarm 或不支持的平台在解析 profile 凭据和发起网络请求前失败。自动化应注入 `login_to_pypi` 的 `confirmation_provider(checkpoint, remaining_seconds)`。任意第三方 callback 必须自行遵守 timeout；API 只在回调前后检查 deadline。

## 已实现：Trusted Publisher 辅助

```bash
chatpypi publisher list
chatpypi publisher detail <project>
chatpypi publisher add-github <project> --owner <owner> --repo <repo> --workflow publish.yml
```

当前重点是给已有 PyPI project 配置 active Trusted Publisher。`pending-*` 只用于新项目注册前 pending 例外或 stale pending 清理。

## 未实现或 checkpoint Flow

以下能力不要写成完全自动化教程：

- PyPI 账号注册。
- 邮箱地址验证（登录的新设备邮件确认检查点已实现）。
- 2FA 初始化和 recovery codes。
- token 创建/删除。
- 需要浏览器、人机验证、二维码或复杂 checkpoint 的流程。

这些能力后续应按 browser-assist / checkpoint 设计，再补真实实践文档。
