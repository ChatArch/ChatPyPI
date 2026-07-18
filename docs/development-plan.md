# 开发计划

## Review Contract

- 模板生成结果必须能在干净目录里直接运行。
- CLI 命令背后必须有可 import 的 Python API。
- Docs 只把已实现/已验证能力写成操作说明；未实现能力保留为路线图。
- 密码、token、session、cookie 不得写进 README、docs、issue、PR 评论或 CI log。
- 远端写操作必须明确权限和 checkpoint 边界。

## 当前完成方向

- ChatArch 模板默认生成 MkDocs Material + static i18n 文档站。
- ChatArch 模板默认使用 `arch.gh.wzhecnu.cn` 文档域名和 `docs/CNAME`。
- 模板支持 `--docs-domain` 和 `--without-docs-cname`。
- Preview Docs workflow 使用 ChatArch Pages 域名生成 `/dev/` 预览地址。

## 后续方向

- 给模板继续补更具体的 Flow 页面时，必须先有真实实现和验证。
- 对 PyPI 注册、2FA、token 创建等 checkpoint-heavy 流程，先设计 browser-assist/checkpoint，再落文档。
- 为生成包增加更完整的 docs smoke 测试时，避免把真实账号或私有域名写入 fixture。
