# Python 接口树

ChatPyPI 的 CLI 应保持薄入口；实质行为放在 `chatpypi.main` 和 `chatpypi.session_ops`。

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
- `docs/CNAME` 显式生成开关。
- PR preview URL。
- 初始 docs 骨架。

## `chatpypi.session_ops`

```text
login_to_pypi
load_session_payload_from_env
validate_session_payload
list_projects_from_session
list_publishers_from_session
publisher_detail_from_payload
add_github_publisher_to_project_from_payload
add_pending_github_publisher_from_payload
remove_pending_github_publisher_from_payload
```

## `chatpypi.cli`

`chatpypi.cli` 负责 Click 参数解析、ChatStyle 交互入口和错误转换。新增实质能力时，优先在 service/API 层实现，再接 CLI。
