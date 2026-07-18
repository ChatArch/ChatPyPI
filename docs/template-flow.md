# ChatArch 模板与 Docs Flow

这个页面记录 `chatpypi init -t chatarch` 的模板创建 Flow。它是已实现能力，当前 PR 重点更新 docs 相关模板规范。

## 目标

生成一个 ChatArch 系列 Python 包时，默认带上：

```text
<package>/
├── pyproject.toml
├── README.md / README.en.md
├── mkdocs.yml
├── docs/
│   ├── CNAME
│   ├── index.md
│   ├── index.en.md
│   ├── cli-tree.md
│   ├── interface-tree.md
│   └── development-plan.md
└── .github/workflows/
    ├── ci.yml
    ├── deploy.yaml
    ├── preview.yaml
    └── publish.yml
```

## 当前命令

```bash
chatpypi init my-package -t chatarch --project-dir ./my-package
```

默认行为：

- 创建 MkDocs Material 配置。
- 接入 `mkdocs-static-i18n` suffix 模式。
- 中文默认站点，英文入口为 `/en/`。
- 缺少英文专题页时 fallback 到中文。
- 创建 `docs/CNAME`，默认域名为 `arch.gh.wzhecnu.cn`。
- PR preview 使用 `mike deploy dev`。
- preview comment 使用 ChatArch Pages 域名。

## 可配置项

```bash
chatpypi init my-package -t chatarch \
  --docs-domain docs.example.com \
  --without-docs-cname
```

| 参数 | 含义 |
| --- | --- |
| `--docs-domain` | 生成 docs URL、preview URL 和 CNAME 使用的域名。默认 `arch.gh.wzhecnu.cn`。 |
| `--with-docs-cname` | 生成 `docs/CNAME`。默认开启。 |
| `--without-docs-cname` | 不生成 `docs/CNAME`，适合不使用 custom domain 的仓库。 |
| `--without-mkdocs` | 不生成 MkDocs/docs 文件。 |
| `--without-workflows` | 不生成 GitHub Actions workflow。 |

## Review 要点

- 模板文档只给骨架和更新指引，不把未实现命令写成已可用操作。
- 生成包的 `pyproject.toml` docs extra 必须包含 `mkdocs-static-i18n`。
- `preview.yaml` 不应再使用 `github.io`。
- `docs/CNAME` 只写域名，不写 scheme 或 path。
- 生成后的 package 应能通过 `mkdocs build --strict`。
