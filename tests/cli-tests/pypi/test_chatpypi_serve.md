# test_chatpypi_serve

验证注册 API 只通过薄 CLI 入口启动，并保留安全默认值。

## 元信息

- 命令：`chatpypi serve`、`chatpypi paths --format json`
- 目的：验证 serve/paths 已注册到真实 ChatStyle CLI 树，且缺少可恢复参数时不引入额外交互。
- 标签：`cli`、`api`
- 前置条件：安装 `.[api]`；使用隔离的 `CHATARCH_HOME`。
- 外部副作用：无；测试不启动监听端口、不访问 PyPI/GitHub。

## 用例

1. `chatpypi --help` 与 `chatpypi --tree` 包含 `serve` 和 `paths`。
2. `chatpypi serve --help` 展示 loopback host/port 选项，不启动 uvicorn。
3. `chatpypi paths --format json` 返回 ChatArch home 下的 registration runtime/state 所有权路径。
4. base extra 未安装 API 依赖时，其余 CLI import 和 `--help` 仍可工作；FastAPI/uvicorn 只在执行 serve 时延迟导入。
5. 未配置 service token 时，`serve` 在创建 listener 前固定失败。
6. 配置 placeholder service token 后，CLI 只把 hardened single-worker 参数交给 uvicorn；测试用 fake `uvicorn.run`，不监听端口。

## 清理

删除测试专用的临时 ChatArch home。
