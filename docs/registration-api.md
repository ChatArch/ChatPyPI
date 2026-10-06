# 注册 API 服务

`chatpypi serve` 提供给其他站点后端调用的 registration-only HTTP API。它没有独立 Web UI，也不应由浏览器直接持有 service、PyPI 或 GitHub 凭据。

## 安装与配置

服务依赖不进入基础 CLI 安装；服务端使用 API extra：

```bash
python -m pip install "ChatPyPI[api]"
chatenv new -t chatpypi-api default
```

`chatpypi-api` 是 ChatEnv 注册的 typed schema，字段如下：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `CHATPYPI_API_TOKEN` | 无 | 所有 `/api/*` 路由的 Bearer token；敏感字段，至少 16 字符 |
| `CHATPYPI_API_HOST` | `127.0.0.1` | 监听地址 |
| `CHATPYPI_API_PORT` | `8765` | 监听端口 |
| `CHATPYPI_API_ALLOWED_HOSTS` | loopback hosts | 允许的 HTTP Host，禁止 wildcard |
| `CHATPYPI_API_ALLOWED_OWNERS` | `ChatArch` | GitHub owner allowlist，逗号分隔 |
| `CHATPYPI_REGISTRATION_ENABLED` | `false` | external registration write 总开关 |
| `CHATPYPI_API_MAX_BODY_BYTES` | `65536` | JSON body 上限 |
| `CHATPYPI_API_MAX_QUEUE` | `32` | queued/running job 上限 |
| `CHATPYPI_API_RATE_LIMIT_PER_MINUTE` | `120` | 每个 client address 的 `/api/*` 请求上限 |

非 loopback 监听必须显式配置可信 Host。`*` 不被接受。运行前还需要服务器已有的 active official-PyPI upload token、official-PyPI web-session token profile 和 GitHub ChatEnv token；preflight 不登录、不刷新、不复制这些凭据。服务固定上传/读回 `pypi.org`，不会采用请求或 `.pypirc` 指定的其他 repository URL。

```bash
chatpypi paths --format json
chatpypi serve
```

`paths` 是本机 operator-only 只读入口，用来确认 state 固定属于 ChatArch home。state directory/workspace 使用 0700，SQLite/lock files 使用 0600；符号链接逃逸会被拒绝。

## HTTP 契约

除最小 `GET /health` 外，所有路由都要求：

```http
Authorization: Bearer <service-token>
```

没有 Swagger/ReDoc/default OpenAPI URL，也没有 CORS；`/api/*` 会拒绝带浏览器 `Origin` 的请求。经认证的 `GET /api/schema` 返回 JSON schema。

| 方法与路径 | 行为 |
| --- | --- |
| `GET /health` | 匿名最小响应 `{"status":"ok"}` |
| `GET /api/capabilities` | registration-only 阶段、固定默认值和写开关 |
| `POST /api/preflight` | 有界名字列表的 PyPI/GitHub/认证只读检查 |
| `POST /api/plans` | 创建不可变注册计划，不发生 external write |
| `POST /api/jobs` | 精确确认并异步提交计划 |
| `GET /api/jobs?limit=20&offset=0` | 有界 job 列表 |
| `GET /api/jobs/{id}` | job、阶段 receipts 与固定安全错误 |
| `GET /api/schema` | 经认证的 OpenAPI JSON |

请求模型拒绝未知字段。调用方不能提交 filesystem path、argv、command、proxy/provider URL、env profile 或 credential。

### Preflight

```json
{
  "names": ["example-package"],
  "owner": "ChatArch"
}
```

每个 item 返回服务端派生的 `normalized_name`、`module_name`，以及：

- `registry.status`: `available`、`occupied` 或 `unknown`；
- `registry.ownership`: 已占用名字的 `owned` / `not_owned` / `unknown`，或新名字的 `not_applicable`；
- `repository.status`: `absent`、`exists` 或 `unknown`；
- `credentials`: `pypi_upload`、`pypi_session`、`github` 的 `ready` / `needs_auth` / `unknown`；
- `github_identity`、`can_plan` 和固定类别的 `blockers`。

404 registry read 才表示 `available`。network/解析不确定性必须是 `unknown`，不能伪装成可注册。

### 不可变计划

```json
{
  "distribution": "example-package",
  "description": "Example package",
  "owner": "ChatArch",
  "visibility": "private"
}
```

`visibility` 默认 `private`；要创建 public repo，调用方必须在计划中明确写 `public`。响应固定并持久化：

- distribution/repository、PEP 503 normalized name、Python module；
- owner、visibility、description；
- `initial_version=0.0.1`、`requires_python=>=3.10`、`template=chatarch`；
- `default_branch=main`、`workflow_filename=publish.yml`；
- 完整 stages、plan digest、`ready` / `blockers`；
- server 生成的 exact `confirmation`。

计划创建本身只读。名字 occupied 或 provider read 为 unknown 时不会创建计划；缺认证可以形成带 `needs_auth` blocker 的计划，但 job 在任何本地或远端 mutation 前进入 `blocked`。

### 幂等提交

```http
POST /api/jobs
Idempotency-Key: <caller-generated-stable-key>
Content-Type: application/json

{
  "plan_id": "<plan-id>",
  "confirmation": "<exact-confirmation-from-plan>"
}
```

同一个 key 与同一个 submission 返回原 job，并设置 `idempotent_replay=true`；同 key 指向其他 submission 时返回 `idempotency_conflict`。同 normalized distribution 的 queued/running/reconciliation job 互斥。`CHATPYPI_REGISTRATION_ENABLED=false` 时提交返回 `registration_disabled`，但 read/preflight/plan 仍可用。

job 读模型固定包含 `id`、`plan_id`、`normalized_name`、`status`、`stage`、`receipts`、`created_at`、`updated_at` 和可选 `error`。`status` 只会是 `queued`、`running`、`blocked`、`failed`、`reconciliation_required` 或 `registered`；提交响应额外包含 `idempotent_replay`。

## Registration-only 工作流

单一 executor writer 按以下顺序执行：

```text
credentials → preflight → scaffold → tests → build_check
→ pypi_upload → pypi_readback → public_install → github_repository → source_push
→ [public_protection] → trusted_publisher → github_readback → registered
```

重要边界：

- job 开始时重新 preflight；只有名字仍然 absent 才执行初始 placeholder upload；
- scaffold/build/check 复用 ChatPyPI Python API；build 使用服务环境中已安装依赖的 no-isolation 模式，tests/build/twine/git 都使用清理过的最小环境、固定 argv、`shell=False`、noninteractive 和有界时间/输出；
- PyPI 精确 `0.0.1` wheel + sdist readback 后，还必须通过官方 Simple index 的无缓存 clean-install、已安装版本与真实 CLI 树验证，才用 ChatGH importable API 创建 GitHub repo；
- 初始源码 push 后，配置并读回 active exact GitHub Trusted Publisher；普通路径不创建 pending Publisher；
- public 计划在初始 push 后立即应用并读回 `main` 保护：要求 PR、review count=0、enforce admins、禁止 force push/删除；缺失保护不能完成。private 计划不自动应用 public 保护；
- 终态前再次读回计划内 visibility、`main` default branch 和保护策略；
- 终态叫 `registered`。它不表示后续 tag/OIDC feature release 已执行。

在首次 external write 前发现缺失/失效认证时，job 得到 `blocked/needs_auth`。一旦 mutation 已开始，后续认证失败、timeout、readback/receipt 失败或进程中断都得到 `reconciliation_required`；服务重启不会自动重放。operator 必须先核对 provider 状态，再决定新的计划/人工处置。

`status` 表示 job 生命周期；非成功终态的 `stage` 保留最后尝试的阶段，`receipts` 只包含已经完成并读回的白名单结果。

## 服务端客户端

其他网站只在自己的后端使用客户端：

```python
import os

from chatpypi.client import RegistrationAPIClient

client = RegistrationAPIClient(
    os.environ["CHATPYPI_SERVICE_URL"],
    token=os.environ["CHATPYPI_SERVICE_TOKEN"],
)

preflight = client.preflight(["example-package"], owner="ChatArch")
plan = client.create_plan(
    "example-package",
    owner="ChatArch",
    visibility="private",
    description="Example package",
)
job = client.create_job(
    plan["id"],
    plan["confirmation"],
    idempotency_key="registration-example-package-001",
)
current = client.get_job(job["id"])
```

客户端不会 retry mutation。service URL/token 只能来自消费方后端私有配置，不能打包进静态前端。

## 明确不在首版范围

首版不会 bump version、创建 tag、触发/宣称 OIDC feature release、部署 Pages、修改消费方站点、切换生产服务或自动恢复不确定 external write。
