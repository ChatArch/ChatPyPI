# Local and service modes

Use the same `chatpypi` CLI locally or dispatch supported tools to a hosted backend. The backend keeps PyPI account credentials; clients use ChatAuth access tokens, not PyPI keys.

| Scenario | Entry | Boundary |
| --- | --- | --- |
| Scaffold, build and check locally | `chatpypi --mode local ...` | Default; no tool server required |
| Central account queries, Publishers and uploads | `chatpypi --mode service ...` | Server-owned account binding; upload artifacts only |
| Programmatic integration | REST or MCP | One CLI-derived catalog and execution adapter |

## Configuration {#configuration}

```bash
python -m pip install 'ChatPyPI[service]'
chatpypi --tree
chatenv set CHATPYPI_MODE=local -I
chatenv set CHATPYPI_BASE_URL=https://tools.example.test -I
chatenv set CHATPYPI_AUTH_PROFILE=tool-client -I
```

These fields extend the existing ChatEnv `pypi` type and `PyPI` namespace. Precedence is explicit CLI options, process environment, active ChatEnv profile, then `local`. To make remote execution the default, set `CHATPYPI_MODE=service`.

```bash
chatpypi --mode local pkg probe ChatPyPI
chatpypi --mode service pkg probe ChatPyPI
chatpypi --mode local pkg build
chatpypi --mode service pkg upload
```

Scaffolding, build/check, mirrors, local config/profiles and PyPI login/session commands stay local even in service mode. Planned placeholders are not exported. Remote failures never fall back to local execution; writes are not retried.

Clients read `values.access_token` from `TokenStore().read("ChatAuth", "tool-client")`; `--auth-profile` selects another profile. `CHATPYPI_ACCESS_TOKEN` supports explicit bootstrap, but must not contain a PyPI key. ChatPyPI does not issue tokens or create another issuer. Automatic remote refresh is not implemented: refresh an expired TokenStore through the ChatAuth authorization flow.

## Serve {#serve}

Configure an existing issuer, audience and JWKS, then map authenticated subjects or clients to server-side PyPI profiles:

```bash
chatenv set CHATPYPI_AUTH_ISSUER=https://auth.example.test -I
chatenv set CHATPYPI_AUTH_AUDIENCE=chatpypi-service -I
chatenv set CHATPYPI_AUTH_JWKS_URL=https://auth.example.test/jwks -I
chatenv set CHATPYPI_AUTH_SCOPE=chatpypi:invoke -I
chatpypi --mode local serve --host 127.0.0.1 --port 8765 \
  --profile-binding tool-client=pypi-account
```

`pypi-account` is an existing server PyPI ChatEnv profile. Queries use its session; uploads use its `PYPI_API_TOKEN`. Requests cannot override that binding. Repeat `--profile-binding` for multiple identities. HTTP refuses to start without authentication. RS256 signatures, issuer, audience, time claims and scope are verified; unbound identities receive 403. Bind to loopback by default and use an existing HTTPS ingress for other machines. Non-loopback HTTP token transport is rejected. Repeat `--allowed-host tools.example.test` to trust actual client-facing Host values; binding `0.0.0.0` does not trust arbitrary hosts. Remote probe requires `package_name`; CLI convenience resolves an omitted name on the client, never from the server directory.

Trusted local processes may use stdio with exactly one bound account:

```bash
chatpypi --mode local serve --transport stdio --profile-binding tool-client=pypi-account
```

Stdio relies on local process authority, not network Bearer verification. Never expose it through an anonymous or untrusted process bridge.

## REST and MCP {#interfaces}

Authenticated `GET /api/tools` returns names, routes, methods and input schemas. Read-only tools support GET query parameters and POST JSON; mutations accept POST only.

```text
/api
├── tools                         # GET: catalog and schemas
├── pkg/probe                     # GET/POST: name preflight
├── pkg/upload                    # POST: upload wheel/sdist
├── project/list                  # GET/POST: account projects
├── publisher/list                # GET/POST: active Publishers
├── publisher/detail              # GET/POST: project details
├── publisher/add-github          # POST: add/verify Publisher
├── publisher/pending-list        # GET/POST: pending Publishers
├── publisher/pending-add         # POST: add pending Publisher
├── publisher/pending-remove      # POST: remove pending Publisher
├── doctor/check                  # GET/POST: bound account check
└── docs/{links,examples,open}     # GET/POST: documentation tools
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

Results contain `tool`, `exit_code`, `stdout` and `stderr`; exit codes preserve CLI semantics. HTTP 401/403/413/422 distinguish authentication, authorization, size and input rejection. MCP names include `pkg_probe`, `pkg_upload` and `project_list`. There is no Swagger/ReDoc UI, plan/job store, queue or registration platform.

Python entrypoints are `chatpypi.service.create_app`, `create_mcp_server` and `chatpypi.tool_service.invoke_tool`. The in-process adapter reuses registered CLI capabilities without invoking a CLI shell and serializes shared output capture. Existing domain APIs remain importable from package modules.

## Upload contract {#upload}

The client collects already-built distributions and sends `artifacts`, each with `filename`, `content_base64`, `size` and `sha256`. Limits are four artifacts, 10 MiB each, 20 MiB total and a 30 MiB HTTP request. Wheel/sdist names only; paths and symlinks are rejected. The server verifies digests, creates an owned temporary dist under ChatArch home, uploads once and cleans up. It neither transfers source nor builds remotely, extracts archives, interprets client directories on the server, or accepts caller credential selectors/custom repository URLs.

Real publishing is an external mutation. Configuring a service is not permission to test publishing; callers retain explicit execution/confirmation conventions. One request invokes one tool, never repository creation, Pages setup or a composite registration workflow.
