# test_chatpypi_basic

测试 `chatpypi` 的基础 CLI 链路，覆盖版本输出、legacy root aliases、`pkg` 命名空间、env-backed session token 读取与手动 token 上传入口。

## 元信息

- 命令：`chatpypi <command> [args]`
- 目的：验证 PyPI 工具板块已接入主 CLI，并具备最小可用的建包、产物校验、session 读取与 token 上传入口能力。
- 标签：`cli`、`e2e`
- 前置条件：本地可执行 Python，临时目录可写。
- 环境准备：创建一个最小 Python 包目录，包含 `pyproject.toml`、`README.md`、`LICENSE`。
- 回滚：删除临时目录。

## 用例 0：顶层版本输出

- 初始环境准备：
  - 当前 `chatpypi` 包可导入。

预期过程和结果：
  1. 执行 `chatpypi --version`。
  2. 预期输出当前包版本，例如 `chatpypi, version 0.2.0`。

参考执行脚本（伪代码）：

```sh
chatpypi --version
```

## 用例 1：init 生成最小 Python 包

- 初始环境准备：
  - 准备一个空目录。
- 相关文件：
  - `<tmp>/mychat/`

预期过程和结果：
  1. 执行 `chatpypi init mychat --project-dir <tmp>/mychat`，预期生成 `pyproject.toml`、`README.md`、`LICENSE`、`src/mychat/__init__.py`、`tests/conftest.py`、`tests/test_version.py`。
  2. default 模板生成的 `pyproject.toml` 默认写入 `requires-python = ">=3.9"`；`chatarch` 模板默认写入 `requires-python = ">=3.10"`。
  3. 在交互终端里缺少包名时，`chatpypi init` 应自动进入交互式补参；显式 `-I` 关闭交互时才报错。

## 用例 1b：`chatarch` 模板应补基础开发规范

- 初始环境准备：
  - 准备一个空目录。
- 相关文件：
  - `<tmp>/mychat-cli/`

预期过程和结果：
  1. 执行 `chatpypi init mychat-cli -t chatarch --project-dir <tmp>/mychat-cli`。
  2. 预期额外生成 `DEVELOP.md`、`CHANGELOG.md`、`AGENTS.md`、`README.en.md`、`mkdocs.yml`、`src/<module>/cli.py`、`docs/index.md`、`docs/index.en.md`、`tests/cli-tests/README.md`、`tests/mock-cli-tests/README.md`、`tests/code-tests/README.md`。
  3. 预期生成 `.github/workflows/ci.yml`、`publish.yml`、`deploy.yaml`、`preview.yaml`。
  4. 默认 README 使用中文，并在开头包含 PyPI version、GitHub Actions 和 mkdocs docs badge；badge、`pyproject.toml` URL 与 `mkdocs.yml` 仓库链接默认指向 `ChatArch/<package>`。
  5. `publish.yml` 只应由 `v*` tag 或手动 `workflow_dispatch` 触发，不应由普通分支 push 触发。
  6. 这些文件应体现 CLI 规范、开发规范、文档/测试约定和自动化基础说明。
  7. 可通过 `--without-mkdocs` 跳过 mkdocs/docs 文件，通过 `--without-workflows` 跳过 `.github/workflows/`。

参考执行脚本（伪代码）：

```sh
chatpypi init mychat --project-dir /tmp/mychat
chatpypi init mychat-cli -t chatarch --project-dir /tmp/mychat-cli
```

## 用例 2：build/check 验证最小包结构

- 初始环境准备：
  - 已完成 `chatpypi init mychat`。
- 相关文件：
  - `<tmp>/mychat/pyproject.toml`
  - `<tmp>/mychat/README.md`
  - `<tmp>/mychat/LICENSE`

预期过程和结果：
  1. 执行 `chatpypi build --project-dir <tmp>/mychat`，预期输出开始日志，并在 `dist/` 下生成构建产物。
  2. 执行 `chatpypi check --project-dir <tmp>/mychat`，预期输出被检查的构建产物列表。

参考执行脚本（伪代码）：

```sh
chatpypi build --project-dir /tmp/mychat
chatpypi check --project-dir /tmp/mychat
```

## 用例 3：生成后可直接运行 pytest

- 初始环境准备：
  - 已完成 `chatpypi init mychat`。
- 相关文件：
  - `<tmp>/mychat/tests/conftest.py`
  - `<tmp>/mychat/tests/test_version.py`

预期过程和结果：
  1. 进入 `<tmp>/mychat` 后执行 `python -m pytest -q`，预期测试通过，不需要手动设置 `PYTHONPATH`。

参考执行脚本（伪代码）：

```sh
cd /tmp/mychat
python -m pytest -q
```

## 用例 4：`pkg upload` 支持手动 token 发布入口

- 初始环境准备：
  - 已完成最小项目构建。
  - 本地环境变量中有 `PYPI_API_TOKEN`。
- 相关文件：
  - `<tmp>/mychat/dist/*`

预期过程和结果：
  1. 执行 `chatpypi pkg upload --project-dir <tmp>/mychat --token-env PYPI_API_TOKEN`。
  2. 预期 CLI 把上传动作路由到 `twine upload`。
  3. 预期 CLI 使用 `__token__` 作为用户名，并通过环境变量把 token 传给 `TWINE_PASSWORD`，而不是把秘密直接拼到命令行里。
  4. 若底层工具输出中包含该 token 值，CLI 对用户展示前必须脱敏为 `[REDACTED]`。

参考执行脚本（伪代码）：

```sh
export PYPI_API_TOKEN=...
chatpypi pkg upload --project-dir /tmp/mychat --token-env PYPI_API_TOKEN
```

## 用例 5：`auth session show` 支持从 `PYPI_SESSION_TOKEN` / ChatEnv 读取 session token

- 初始环境准备：
  - 已有一个由 `chatpypi auth login` 生成的 `PYPI_SESSION_TOKEN`，该值可来自当前进程环境或 active ChatEnv PyPI profile。

预期过程和结果：
  1. 执行 `chatpypi auth session show --format json`。
  2. 预期 CLI 自动读取 `PYPI_SESSION_TOKEN` / active ChatEnv，不需要外部 session 文件。
  3. 预期输出非敏感摘要，如 `username`、`cookie_count`、`has_last_seen_csrf`，而不是直接回显 cookie 内容。

参考执行脚本（伪代码）：

```sh
chatpypi auth login --password-env PYPI_PASSWORD --totp-env PYPI_TOTP_SECRET
chatpypi auth session show --format json
```

## 用例 6：缺失 secret 环境变量时给出明确错误

- 初始环境准备：
  - 已完成最小项目构建。
  - 没有设置 `PYPI_API_TOKEN`。

预期过程和结果：
  1. 执行 `chatpypi pkg upload --project-dir <tmp>/mychat --token-env PYPI_API_TOKEN`。
  2. 预期 CLI 直接失败，不进入 `twine upload`。
  3. 预期错误消息明确指出 `PYPI_API_TOKEN` 未设置，便于用户修正 env 配置。

## 用例 7：无效 session token 必须给出明确错误

- 初始环境准备：
  - `PYPI_SESSION_TOKEN` 存在但不是 ChatPyPI 可解析的 session token。

预期过程和结果：
  1. 执行 `chatpypi auth session show`。
  2. 预期 CLI 非 0 退出。
  3. 预期错误消息明确指出 `PYPI_SESSION_TOKEN` 无效，不能抛出 traceback。

## 用例 8：预留操作命令不能成功退出

- 初始环境准备：
  - 当前命令树包含未来预留的操作命令，例如 `token create`。

预期过程和结果：
  1. 执行 `chatpypi token create`。
  2. 预期 CLI 非 0 退出。
  3. 预期错误消息明确指出该命令尚未实现，避免自动化误判为成功执行。

## 清理 / 回滚

- 删除临时目录。
