# 本地与服务模式

同一个 `chatpypi` 命令可以在本机执行，也可以把支持的工具调用发送到服务端。服务端保管 PyPI 账号凭据，客户端只使用 ChatAuth access token。

| 场景 | 入口 | 执行边界 |
| --- | --- | --- |
| 本机创建、构建、检查 | `chatpypi --mode local ...` | 默认本地，不需要工具服务 |
| 集中账号查询、Publisher、上传 | `chatpypi --mode service ...` | 服务端绑定账号；上传只传产物 |
| 其他程序直接接入 | REST 或 MCP | 共用 CLI 派生的工具目录与执行适配器 |

## 安装与默认模式 {#configuration}

```bash
python -m pip install 'ChatPyPI[service]'
chatpypi --tree
chatenv set CHATPYPI_MODE=local -I
chatenv set CHATPYPI_BASE_URL=https://tools.example.test -I
chatenv set CHATPYPI_AUTH_PROFILE=tool-client -I
```

这些字段属于现有 ChatEnv `pypi` 类型、`PyPI` 存储命名空间。模式读取顺序是显式参数、进程环境、当前 ChatEnv profile、默认 `local`；不另建一套配置目录。切为默认远程只需 `chatenv set CHATPYPI_MODE=service -I`。

```bash
chatpypi --mode local pkg probe ChatPyPI
chatpypi --mode service pkg probe ChatPyPI
chatpypi --mode local pkg build
chatpypi --mode service pkg upload
```

`pkg init/build/check`、`mirror`、本机配置/profile、PyPI 登录与本机会话仍是本地操作，`service` 不把本地源码或凭据隐式搬到服务端。占位命令不导出为 API。远程失败不会自动改为本地执行，也不会重试写操作。

客户端从 `TokenStore().read("ChatAuth", "tool-client")` 的 `values.access_token` 读取访问令牌；可通过 `--auth-profile` 覆盖 profile。显式引导时也支持 `CHATPYPI_ACCESS_TOKEN`，不把真实 PyPI key 放到这个字段。ChatPyPI 不签发 token，也不内置新的 ChatAuth issuer；当前不自动进行远程 refresh，过期时应由 ChatAuth 授权流程刷新该 TokenStore。

## 启动服务 {#serve}

服务端需要已有 ChatAuth issuer、audience、JWKS 和身份到账户的绑定：

```bash
chatenv set CHATPYPI_AUTH_ISSUER=https://auth.example.test -I
chatenv set CHATPYPI_AUTH_AUDIENCE=chatpypi-service -I
chatenv set CHATPYPI_AUTH_JWKS_URL=https://auth.example.test/jwks -I
chatenv set CHATPYPI_AUTH_SCOPE=chatpypi:invoke -I
chatpypi --mode local serve --host 127.0.0.1 --port 8765 \
  --profile-binding tool-client=pypi-account
```

`pypi-account` 是服务端已配置的 PyPI ChatEnv profile；查询使用其会话，上传使用其 `PYPI_API_TOKEN`，请求不能选择或覆盖账号。`--profile-binding` 可重复设置不同 subject/client 的映射。没有鉴权配置时 HTTP 服务拒绝启动；RS256 签名、issuer、audience、时间与 scope 均验证。不同身份无绑定时返回 403。默认只绑定 loopback；跨机器应由已有 HTTPS 入口代理，不能把 access token 通过普通远程 HTTP 发送。`--allowed-host tools.example.test` 指定客户端实际使用的 Host，可重复；监听 `0.0.0.0` 时不会自动信任所有 Host。远程 probe 接口必须提供 `package_name`；CLI 省略时先在客户端读取项目名，不读服务端目录。

受信任的本机 MCP 进程可用 stdio，必须明确绑定唯一服务端账号：

```bash
chatpypi --mode local serve --transport stdio --profile-binding tool-client=pypi-account
```

stdio 是本机进程权限边界，不是网络 Bearer 验证；不要把它接到匿名或不受信任的进程入口。

## REST 与 MCP 接口 {#interfaces}

`GET /api/tools` 返回鉴权后的工具名称、路径、方法与输入 JSON Schema。以下只读路径支持 GET query 参数，也支持 POST JSON；变更只接受 POST。

```text
/api
├── tools                         # GET：目录与 schema
├── pkg/probe                     # GET/POST：包名预检
├── pkg/upload                    # POST：上传 wheel/sdist
├── project/list                  # GET/POST：账号项目
├── publisher/list                # GET/POST：active Publisher
├── publisher/detail              # GET/POST：指定项目详情
├── publisher/add-github          # POST：添加/确认 GitHub Publisher
├── publisher/pending-list        # GET/POST：pending Publisher
├── publisher/pending-add         # POST：添加 pending Publisher
├── publisher/pending-remove      # POST：移除 pending Publisher
├── doctor/check                  # GET/POST：绑定账号检查
└── docs/{links,examples,open}     # GET/POST：现有文档工具
/mcp/                            # MCP StreamableHTTP
```

```python
import os
import httpx

headers = {"Authorization": f"Bearer {os.environ['CHATPYPI_ACCESS_TOKEN']}"}
with httpx.Client(base_url="https://tools.example.test", headers=headers, timeout=20) as client:
    tools = client.get("/api/tools").raise_for_status().json()
    result = client.get("/api/pkg/probe", params={"package_name": "ChatPyPI"}).raise_for_status().json()
    print(result["exit_code"], result["stdout"])
```

返回 `tool`、`exit_code`、`stdout`、`stderr`；工具退出码与 CLI 对齐，HTTP 401/403/413/422 区分鉴权、权限、大小与参数拒绝。MCP 名称为 `pkg_probe`、`pkg_upload`、`project_list` 等，与目录一致。HTTP/MCP 无 Swagger/ReDoc 页面，也没有 plans、jobs、队列或注册平台。

Python 可导入 `chatpypi.service.create_app`、`create_mcp_server` 和 `chatpypi.tool_service.invoke_tool`。执行适配器在进程内复用已注册 CLI 能力，不启动 CLI shell；共享输出捕获串行化。底层领域 API 保留在现有包模块中。

## 上传边界 {#upload}

本地 `pkg upload` 收集已构建的 dist，发送 `artifacts`，每项包含 `filename`、`content_base64`、`size`、`sha256`。限制为最多 4 项、单项 10 MiB、合计 20 MiB；HTTP 请求上限 30 MiB。只允许 wheel/sdist 文件名、拒绝路径与软链接；服务端验证摘要，在 ChatArch home 内创建受控临时 dist，上传后清理。不发送源码、不远程 build、不解压产物、不把客户端项目目录解释成服务端路径；不接受客户端 repository URL 或凭据选择器。

真实发布仍有外部写入后果。配置服务不等于授权测试发布；调用方应沿用工具的显式执行/确认约定。服务只负责一次工具调用，不自动创建仓库、配置 Pages 或执行复合注册流水线。
