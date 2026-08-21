# ChatArch 模板与 Docs Flow

这个页面记录 `chatpypi init -t chatarch` 的模板创建 Flow。它是已实现能力，当前 PR 重点更新 docs 相关模板规范。

## 目标

生成一个 ChatArch 系列 Python 包时，默认带上结构化占位，而不是具体项目计划或仓库级域名文件：

```text
<package>/
├── pyproject.toml
├── README.md / README.en.md
├── mkdocs.yml
├── docs/
│   ├── index.md
│   ├── index.en.md
│   ├── cli-tree.md
│   ├── cli-tree.en.md
│   ├── capability-map.md
│   ├── capability-map.en.md
│   └── interface-tree.md
└── .github/workflows/
    ├── ci.yml
    ├── deploy.yaml
    ├── preview.yaml
    └── publish.yml
```

默认文档只保留长期有用的结构槽位：首页导航、CLI 树、能力地图和 Python 接口树。

## 当前命令

```bash
chatpypi init my-package -t chatarch --project-dir ./my-package
```

默认行为：

- 创建 MkDocs Material 配置。
- 接入 `mkdocs-static-i18n` suffix 模式。
- 中文默认站点，英文内容放在 `.en.md` 文件和语言切换入口里。
- 生成首页导航、CLI 树、能力地图和 Python 接口树。
- 依赖 `chatstyle>=0.2.0,<0.3.0` 与 `chatenv>=0.2.11,<0.3.0`，并通过 ChatStyle 共享运行时提供 `--tree` 和 `--tree-brief`。
- 生成 CI、发布、Preview Docs 和 Deploy Docs workflow。
- CI 对生成包的 `--version`、`--tree` 和 `--tree-brief` 做 smoke readback。
- PR preview 使用 `mike deploy dev`。
- preview comment 使用 ChatArch Pages 域名。

## 可配置项

```bash
chatpypi init my-package -t chatarch \
  --docs-domain docs.example.com
```

| 参数 | 含义 |
| --- | --- |
| `--docs-domain` | 生成 docs URL、badge、preview URL 和 metadata 使用的域名。默认 `arch.gh.wzhecnu.cn`。 |
| `--without-mkdocs` | 不生成 MkDocs/docs 文件。 |
| `--without-workflows` | 不生成 GitHub Actions workflow。 |

## Review 要点

- 模板文档可以是占位，但占位必须引导到正确结构：首页导航、CLI 树、能力地图和接口树。
- 默认中文页面保持中文语境；英文内容只放在 `.en.md` 和语言切换入口里。
- CLI 树回答“怎么调用”：真实命令树、命令状态、交互约定和更新清单；它是最直观的命令展示入口。
- 默认 `--tree` 保留参数签名；`--tree-brief` 只保留命令节点和描述。
- 能力地图回答“包负责什么”：一等能力、验证状态、能力边界和不负责的范围。
- 生成包的 `pyproject.toml` docs extra 必须包含 `mkdocs-static-i18n`。
- `mkdocs.yml` 必须启用 `attr_list` 和 `md_in_html`，支持 Material grid cards。
- `preview.yaml` 不应再使用 `github.io`。
- 生成后的 package 应能通过 `mkdocs build --strict`。
