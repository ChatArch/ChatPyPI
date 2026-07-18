# ChatPyPI 文档

ChatPyPI 是 ChatArch 的 Python 包生命周期和 PyPI 自动化 CLI/API 包。它负责包模板创建、构建校验、上传、PyPI 登录态管理、项目读取和 Trusted Publisher 配置辅助。

站点入口： https://arch.gh.wzhecnu.cn/ChatPyPI/

## 按场景选择文档

| 场景 | 文档 | 状态 |
| --- | --- | --- |
| 创建 ChatArch Python 包模板，并生成 MkDocs / i18n / Actions / CNAME | [ChatArch 模板与 Docs Flow](template-flow.md) | 已实现，当前 PR 更新模板规范 |
| 构建、检查、上传 Python 包，或配置 Trusted Publisher | [发布与 Trusted Publisher Flow](pypi-flow.md) | 部分已实现，部分保留人工 checkpoint |
| 查看当前命令树和未实现边界 | [CLI 能力地图](cli-tree.md) | 已整理 |
| 查看 CLI 背后的 Python 接口边界 | [Python 接口树](interface-tree.md) | 已整理 |
| 维护后续路线和 review 合约 | [开发计划](development-plan.md) | 已整理 |

## 文档组织

当前文档按 ChatArch 文档规范组织：

- **模板创建**：ChatPyPI 作为模板生成器时应该创建哪些 docs、workflow 和配置。
- **PyPI 发布**：包生命周期、登录态、项目和 Trusted Publisher 操作 Flow。
- **CLI / API**：命令树、Python API 映射和薄 CLI 约束。
- **路线图**：只记录未实现能力的设计方向和保护要求。

## 状态约定

- **已实现**：代码、测试或 CLI 路径已经存在。
- **已验证**：通过单测、CI、本地 smoke 或真实 PyPI/Pages 实践验证。
- **未实现**：只写规划和安全边界，不写成可执行教程；实现并验证后再更新为操作文档。

## 当前主命令

```bash
chatpypi --version
chatpypi init --help
chatpypi pkg --help
chatpypi auth --help
chatpypi publisher --help
```

## 本地预览

```bash
python -m pip install -e ".[docs]"
mkdocs serve
```

英文首页见： https://arch.gh.wzhecnu.cn/ChatPyPI/en/。
