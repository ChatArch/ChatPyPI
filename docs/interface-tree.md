# Python 接口树

ChatPyPI 的 CLI 应保持薄入口；实质行为放在 `chatpypi.main`、`chatpypi.session_ops` 和 `chatpypi.mirror_ops`。

## `chatpypi.mirror_ops`

```text
resolve_user_config_paths
show_mirrors
set_mirrors
MirrorConfigError
```

这些 API 管理 uv / pip 原生当前用户配置；支持 `home`、`platform`、`env` 和显式路径注入。返回值只暴露 public preset URL，自定义 URL 固定脱敏。

## `chatpypi.main`

```text
scaffold_package
build_package
check_distributions
upload_distributions
check_repository_conflicts
read_project_metadata
resolve_dist_dir
```

其中 `scaffold_package` 是模板创建核心。当前 docs template 更新主要影响：

- ChatArch docs URL 默认域名。
- MkDocs Material + static i18n 配置。
- PR preview URL。
- 初始 docs 骨架。

## `chatpypi.session_ops`

```text
login_to_pypi
EmailConfirmationCheckpoint
EmailConfirmationRequiredError
EmailConfirmationTimeoutError
EmailConfirmationCancelledError
InvalidEmailConfirmationError
PyPIAuthenticationError
PyPINetworkError
load_session_payload_from_env
validate_session_payload
list_projects_from_session
list_publishers_from_session
publisher_detail_from_payload
add_github_publisher_to_project_from_payload
add_pending_github_publisher_from_payload
remove_pending_github_publisher_from_payload
```

`login_to_pypi` 的邮件确认扩展签名为 `confirmation_provider(checkpoint, remaining_seconds)` 与 `confirmation_timeout=600`。provider 返回完整 HTTPS 确认链接；checkpoint 只包含 origin/path，不包含 token。API 复用同一 requests Session、冻结本次尝试的代理选择、手动限制同 origin 跳转，并在返回常规 `(payload, encoded_token)` 前从真实 account 响应证明用户名一致。

deadline 对任意第三方 callback 是协作式契约：调用前后会检查超时，但 Python API 不会用线程或进程假装可中断任意 callback。CLI 的 `chatpypi.prompt_ops.ask_email_confirmation_url` 是窄范围 POSIX 主线程适配器，使用 ChatStyle 隐藏输入和 scoped timer，并恢复 signal/timer/终端状态。

## `chatpypi.config`

`resolve_pypi_proxy_url()` 从所选 profile / 环境中读取可选 `PYPI_PROXY_URL`；配置通过 ChatEnv 管理。`login_to_pypi(..., proxy_url=...)` 可显式指定代理。加载 token profile 后，网页管理请求在内存中绑定同一 profile 的传输设置，JSON 序列化不包含此绑定。

`RegistrationAPIConfig` 注册独立 `chatpypi-api` typed schema。service token、bind/Host、owner allowlist、write gate 和资源上限只从 operator 配置读取，不能由 HTTP payload 选择。

## `chatpypi.registration`

```text
RegistrationManager
ServiceConfig
RegistrationError
DefaultLocalOps
DefaultProviderBackend
BoundedRunner
load_service_config
normalize_distribution_name
registration_paths
```

`RegistrationManager` 是可导入的 registration-only workflow：immutable plan、SQLite job/receipt、单 executor writer、normalized-name exclusion，以及 interrupted/external outcome reconciliation。默认 provider adapter 复用 ChatPyPI scaffold/build/check/upload/session API 和 ChatGH importable API；只有 git/build/test/twine 使用固定 argv subprocess。

## `chatpypi.api` / `chatpypi.client`

```text
create_app
RegistrationAPIClient
RegistrationAPIError
```

`create_app()` 不启动监听器；`chatpypi serve` 才把它交给 uvicorn。`RegistrationAPIClient` 是无 mutation retry 的服务端 JSON client。最终 HTTP 契约见 [注册 API 服务](registration-api.md)。

## `chatpypi.cli`

`chatpypi.cli` 负责 Click 参数解析、ChatStyle 交互入口和错误转换。新增实质能力时，优先在 service/API 层实现，再接 CLI。
