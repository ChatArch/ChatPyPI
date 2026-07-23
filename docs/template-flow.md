# ChatArch 模板与 Docs Flow

这个页面记录 `chatpypi init -t chatarch` 的模板创建 Flow。它是已实现能力，当前 PR 重点更新 docs 相关模板规范。

## 目标

生成一个 ChatArch 系列 Python 包时，默认带上结构化占位，而不是具体项目计划：

```text
<package>/
├── pyproject.toml
├── README.md / README.en.md
├── mkdocs.yml
├── docs/
│   ├── index.md
│   ├── index.en.md
│   ├── commands.md
│   ├── commands.en.md
│   ├── capability-map.md
│   ├── capability-map.en.md
│   └── interface-tree.md
└── .github/workflows/
    ├── ci.yml
    ├── deploy.yaml
    ├── preview.yaml
    └── publish.yml
```

默认不生成 `docs/development-plan.md`、`docs/cli-tree.md` 或 `docs/CNAME`。

## 当前命令

```bash
chatpypi init my-package -t chatarch --project-dir ./my-package
```

默认行为：

- 创建 MkDocs Material 配置。
- 接入 `mkdocs-static-i18n` suffix 模式。
- 中文默认站点，英文内容放在 `.en.md` 文件和语言切换入口里。
- 生成首页导航、命令地图、能力地图和 Python 接口树。
- 不默认创建 `docs/CNAME`；只有显式传 `--with-docs-cname` 才生成。
- PR preview 使用 `mike deploy dev`。
- preview comment 使用 ChatArch Pages 域名。

## 可配置项

```bash
chatpypi init my-package -t chatarch \
  --docs-domain docs.example.com \
  --with-docs-cname
```

| 参数 | 含义 |
| --- | --- |
| `--docs-domain` | 生成 docs URL 和 preview URL 使用的域名。默认 `arch.gh.wzhecnu.cn`。 |
| `--with-docs-cname` | 显式生成 `docs/CNAME`，仅用于这个仓库确实需要管理自定义域名文件的情况。 |
| `--without-docs-cname` | 保持不生成 `docs/CNAME`。这是当前默认行为。 |
| `--without-mkdocs` | 不生成 MkDocs/docs 文件。 |
| `--without-workflows` | 不生成 GitHub Actions workflow。 |

## Review 要点

- 模板文档可以是占位，但占位必须引导到正确结构：首页导航、命令地图、能力地图和接口树。
- 默认中文页面保持中文语境；英文内容只放在 `.en.md` 和语言切换入口里。
- 命令地图回答“怎么调用”：真实命令树、命令状态、交互约定和更新清单。
- 能力地图回答“包负责什么”：一等能力、验证状态、能力边界和不负责的范围。
- 生成包的 `pyproject.toml` docs extra 必须包含 `mkdocs-static-i18n`。
- `mkdocs.yml` 必须启用 `attr_list` 和 `md_in_html`，支持 Material grid cards。
- `preview.yaml` 不应再使用 `github.io`。
- 如果显式生成 `docs/CNAME`，文件只写域名，不写 scheme 或 path。
- 生成后的 package 应能通过 `mkdocs build --strict`。
