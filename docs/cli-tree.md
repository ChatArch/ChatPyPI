# ChatPyPI CLI 能力地图

这篇文档是当前 ChatPyPI CLI 的简明能力地图，用来校对哪些 Python 包生命周期、PyPI 登录态和 Trusted Publisher 流程已经有一等命令，哪些流程仍然只是 checkpoint / 规划入口。

可导入 Python 函数映射见 [Python 接口树](interface-tree.md)。模板创建行为见 [ChatArch 模板与 Docs Flow](template-flow.md)。发布和 Trusted Publisher 实践见 [发布与 Trusted Publisher Flow](pypi-flow.md)。

## 顶层命令

```text
chatpypi                  # Python 包生命周期与 PyPI 操作入口
├── --help                # 显示当前命令帮助
├── --version             # 输出当前包版本
├── --tree                # 输出带参数签名的真实已注册 CLI 树
├── --tree-brief          # 输出命令节点和描述，不含参数签名
├── pkg                   # 包模板、构建、校验、上传和探测
├── auth                  # 登录态、账号和人工 checkpoint 流程
├── profile               # 规划：本地 ChatPyPI profile 管理
├── config                # 规划：本地配置键值管理
├── project               # 读取当前登录账号的 PyPI project 视图
├── publisher             # 读取或配置 Trusted Publisher
├── token                 # 规划 / checkpoint：PyPI API token 管理
├── doctor                # 本地配置、session 和安全边界检查
├── docs                  # 输出文档链接和示例命令
├── init                  # 兼容快捷入口：创建 src-layout Python 包
├── build                 # 兼容快捷入口：构建 wheel / sdist
├── check                 # 兼容快捷入口：校验 dist
├── upload                # 兼容快捷入口：上传 dist
└── probe                 # 兼容快捷入口：检查 PyPI 包名是否可用
```

`chatpypi --tree` 和 `chatpypi --tree-brief` 由 ChatStyle 的 `add_tree_option()` 提供，并通过共享 `render_click_tree()` 回读注册树。默认树保留参数签名；简明树保留命令节点和描述，但省略参数签名。`pkg init -t chatarch` 生成的新包也包含这两个顶层选项。

## 包生命周期

```text
chatpypi pkg              # 包生命周期主分组
├── init                  # 创建 default 或 chatarch 模板包
├── build                 # 构建 wheel / sdist；可先清理 dist
├── check                 # 调用 twine check 校验构建产物
├── upload                # 用 token env / password env 上传 dist
└── probe                 # 查询 PyPI 包名冲突

chatpypi init             # 兼容 `chatpypi pkg init`
chatpypi build            # 兼容 `chatpypi pkg build`
chatpypi check            # 兼容 `chatpypi pkg check`
chatpypi upload           # 兼容 `chatpypi pkg upload`
chatpypi probe            # 兼容 `chatpypi pkg probe`
```

`pkg init -t chatarch` 是当前模板更新的核心入口：它生成 README、MkDocs、CLI 树、能力地图、接口树、CI/Preview/Deploy workflow 和 ChatEnv provider。默认文档只保留结构化占位，不生成计划页或仓库级域名文件。

## 认证和 Session

```text
chatpypi auth             # 登录态、账号和引导型操作
├── login                 # 用户名/密码/TOTP 登录，并写入 ChatEnv token profile
├── logout                # 清理本地 session token-store state
├── whoami                # 用 session 读回当前账号摘要
├── register              # 规划 / checkpoint：账号注册
├── verify-email          # 规划 / checkpoint：邮箱验证
├── setup-2fa             # 规划 / checkpoint：2FA 初始化
├── recovery-codes        # 规划 / checkpoint：恢复码处理
└── session               # token-backed PyPI session 管理
    ├── show              # 输出非敏感 session 摘要
    ├── export            # 规划 / checkpoint：导出 session
    ├── import            # 规划 / checkpoint：导入 session
    └── clear             # 清理 session token-store state
```

认证命令必须遵守安全边界：密码、TOTP secret、session runtime state、cookie 只通过 env/profile/private store 读取或写入，CLI 和文档都不能回显真实值。`auth login`、`auth whoami` 和 `auth session show|clear` 是当前已实现主路径；注册、邮箱验证、2FA 初始化和恢复码仍然是人工 checkpoint。

## Project 和 Trusted Publisher

```text
chatpypi project          # 当前登录账号的 PyPI project 视图
├── list                  # 已实现：读取项目列表
└── show                  # 规划：显示单个项目详情

chatpypi publisher        # Trusted Publisher 读取与写入
├── list                  # 已实现：读取账号级 publisher 状态
├── detail                # 已实现：读取项目级 publisher 状态
├── add-github            # 已实现：添加/幂等确认 active GitHub publisher
├── pending-list          # 已实现：读取 pending publishers
├── pending-add           # 已实现：添加 pending publisher 例外
└── pending-remove        # 已实现：清理 pending publisher
```

普通路径是已有 PyPI project 的 active Trusted Publisher：使用 `publisher add-github` 写入并读回确认。`pending-*` 只用于真正 pending 的例外流程或清理 stale pending，不是普通 Publisher 默认路径。

## Profile、Config 和 Token 边界

```text
chatpypi profile          # 规划：本地 ChatPyPI profile 管理
├── list                  # 规划：列出 profile
├── show                  # 规划：显示非敏感 profile 字段
├── use                   # 规划：切换 active profile
├── create                # 规划：创建 profile
└── delete                # 规划：删除 profile

chatpypi config           # 规划：本地配置键值管理
├── list                  # 规划：列出配置
├── get                   # 规划：读取配置
├── set                   # 规划：写入配置
└── unset                 # 规划：删除配置

chatpypi token            # 规划 / checkpoint：PyPI API token 管理
├── list                  # 规划：列出 token 摘要，不回显 token
├── create                # 规划：创建 token 并安全保存一次性 secret
└── revoke                # 规划：确认后撤销 token
```

这些命令是预留的一等入口，但不是已实现自动化教程。尤其是 token 创建 / 撤销涉及 PyPI 页面、一次性 secret 和权限确认，在实现和验证前只能写边界，不能写成“可执行操作”。

## 诊断和文档入口

```text
chatpypi doctor           # 本地配置与 session 诊断
└── check                 # 已实现：检查配置、session 和安全边界

chatpypi docs             # 文档链接与示例
├── links                 # 输出核心文档链接
├── examples              # 输出常用示例命令
└── open                  # 输出指定 topic 的文档 URL
```

`doctor check` 用来做本地状态和 session 读回前置检查。`docs` 分组不执行远端写操作，只提供文档入口和示例命令，方便从 CLI 回到文档站。

## 实现合约

- 每个已实现命令都要能追到 Python 函数或 service 层，不能把业务逻辑只堆在 Click 回调里。
- 如果命令会写远端状态，文档必须说明凭据、权限、dry-run/checkpoint 或确认边界。
- 未实现入口只写边界说明，不放可执行教程。
- CLI 树新增命令时，README、接口树、测试和相关 Flow 页面要同步更新。
