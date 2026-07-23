# ChatPyPI 文档

ChatPyPI 是 ChatArch 的 Python 包生命周期和 PyPI 自动化命令行工具。它负责包模板创建、构建校验、上传、PyPI 登录态管理、项目读取和 Trusted Publisher 配置辅助。

站点入口： https://arch.gh.wzhecnu.cn/ChatPyPI/

## 按场景选择文档

| 场景 | 文档 | 状态 |
| --- | --- | --- |
| 一眼查看 ChatPyPI 支持哪些命令 | [CLI 树](cli-tree.md) | 已整理，作为命令面主入口 |
| 创建 ChatArch Python 包模板，并生成 MkDocs / i18n / Actions | [ChatArch 模板与 Docs Flow](template-flow.md) | 已实现，当前 PR 更新模板规范 |
| 构建、检查、上传 Python 包，或配置 Trusted Publisher | [发布与 Trusted Publisher Flow](pypi-flow.md) | 部分已实现，部分保留人工 checkpoint |
| 查看命令背后的 Python 接口边界 | [Python 接口树](interface-tree.md) | 已整理 |

## 核心入口

<div class="grid cards" markdown>

- **CLI 树**

    最直观的命令展示入口。先看树，再判断要进入包生命周期、登录态、Publisher、token 还是 docs 分组。

    [查看 CLI 树](cli-tree.md)

- **模板 Flow**

    校对 `chatpypi init -t chatarch` 默认生成哪些文档槽位和 workflow。

    [查看模板 Flow](template-flow.md)

- **发布 Flow**

    梳理构建、校验、上传、Trusted Publisher 和登录态相关操作。

    [查看发布 Flow](pypi-flow.md)

- **Python 接口树**

    追踪命令背后的可 import 函数和 service 层，避免逻辑只写在命令回调里。

    [查看接口树](interface-tree.md)

</div>

## 文档组织

当前文档按 ChatArch 文档规范组织：

- **CLI 树**：命令树、状态、命令分组和 checkpoint 边界。
- **模板创建**：ChatPyPI 作为模板生成器时应该创建哪些 docs、workflow 和配置。
- **PyPI 发布**：包生命周期、登录态、项目和 Trusted Publisher 操作 Flow。
- **命令与接口**：命令树、Python 接口映射和薄命令行约束。

## 状态约定

- **已实现**：代码、测试或命令路径已经存在。
- **已验证**：通过单测、CI、本地 smoke 或真实 PyPI/Pages 实践验证。
- **规划 / checkpoint**：只写边界和安全说明，不写成可执行教程；实现并验证后再更新为操作文档。

## 当前主命令

```bash
chatpypi --version
chatpypi --help
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
