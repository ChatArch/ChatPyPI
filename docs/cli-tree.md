# CLI 树

CLI 树是 ChatPyPI 文档里最直观的命令入口。读者应该先通过这棵树看到当前支持哪些能力，再进入发布 Flow、接口树或具体命令说明。

状态约定：

- **已实现**：命令路径已经注册，且能追到 Python 函数或 service 层。
- **已验证**：命令已有测试、本地 smoke、CI 或真实 PyPI/Pages 实践。
- **规划 / checkpoint**：命令只保留入口和边界说明；不能写成可自动执行教程。

## 当前命令树

```text
chatpypi                                      # Python 包生命周期与 PyPI 操作入口
├── --version                                 # 输出当前 ChatPyPI 版本
├── init                                      # 兼容入口：创建 src-layout Python 包
├── build                                     # 兼容入口：构建 wheel / sdist
├── check                                     # 兼容入口：twine check 校验 dist
├── upload                                    # 兼容入口：手动 token 上传 dist
├── probe                                     # 兼容入口：检查包名是否可用
├── pkg                                      # 包生命周期主分组
│   ├── init                                  # 创建 default 或 chatarch 模板包
│   ├── build                                 # 构建 wheel / sdist，可清理 dist
│   ├── check                                 # 校验构建产物
│   ├── upload                                # 手动 token / password env 上传
│   └── probe                                 # 查询 PyPI 包名冲突
├── auth                                     # 登录态、账号和引导型操作
│   ├── login                                 # 用户名/密码/TOTP 登录并写入 session token
│   ├── logout                                # 清理本地 session token
│   ├── whoami                                # 用 session 读回当前账号摘要
│   ├── register                              # 规划 / checkpoint：账号注册
│   ├── verify-email                          # 规划 / checkpoint：邮箱验证
│   ├── setup-2fa                             # 规划 / checkpoint：2FA 初始化
│   ├── recovery-codes                        # 规划 / checkpoint：恢复码处理
│   └── session                               # env-backed session 管理
│       ├── show                              # 输出非敏感 session 摘要
│       ├── export                            # 规划 / checkpoint：导出 session
│       ├── import                            # 规划 / checkpoint：导入 session
│       └── clear                             # 清理 session token
├── profile                                  # 规划：本地 ChatPyPI profile 管理
│   ├── list                                  # 规划：列出 profile
│   ├── show                                  # 规划：显示非敏感 profile 字段
│   ├── use                                   # 规划：切换 active profile
│   ├── create                                # 规划：创建 profile
│   └── delete                                # 规划：删除 profile
├── config                                   # 规划：本地配置键值管理
│   ├── list                                  # 规划：列出配置
│   ├── get                                   # 规划：读取配置
│   ├── set                                   # 规划：写入配置
│   └── unset                                 # 规划：删除配置
├── project                                  # 当前登录账号的 PyPI project 视图
│   ├── list                                  # 已实现：读取项目列表
│   └── show                                  # 规划：显示单个项目详情
├── publisher                                # Trusted Publisher 读取与写入
│   ├── list                                  # 已实现：读取账号级 publisher 状态
│   ├── detail                                # 已实现：读取项目级 publisher 状态
│   ├── add-github                            # 已实现：添加/幂等确认 active GitHub publisher
│   ├── pending-list                          # 已实现：读取 pending publishers
│   ├── pending-add                           # 已实现：添加 pending publisher 例外
│   └── pending-remove                        # 已实现：清理 pending publisher
├── token                                    # 规划 / checkpoint：PyPI API token 管理
│   ├── list                                  # 规划：列出 token 摘要，不回显 token
│   ├── create                                # 规划：创建 token 并安全保存一次性 secret
│   └── revoke                                # 规划：确认后撤销 token
├── doctor                                   # 本地配置与 session 诊断
│   └── check                                 # 已实现：检查配置、session 和安全边界
└── docs                                     # 文档链接与示例
    ├── links                                 # 输出核心文档链接
    ├── examples                              # 输出常用示例命令
    └── open                                  # 输出指定 topic 的文档 URL
```

## 能力分组

<div class="grid cards" markdown>

- **包生命周期**

    `pkg init/build/check/upload/probe` 是 ChatPyPI 的基础闭环，用于创建、构建、校验、上传和探测 Python 包。

- **登录后读取**

    `auth whoami`、`project list`、`publisher list/detail` 依赖登录 session，只输出非敏感摘要和结构化状态。

- **Publisher 写入**

    `publisher add-github` 面向已存在 PyPI project 的 active Trusted Publisher；pending 命令只处理真正 pending 的例外或清理。

- **Checkpoint 流程**

    注册、邮箱验证、2FA、token 创建/撤销等仍是 checkpoint-heavy 流程，文档只能写边界，不能伪装成全自动教程。

</div>

## 文档更新规则

- 每个已实现命令都要能追到 Python 函数或 service 层。
- 如果命令会写远端状态，文档必须说明凭据、权限、dry-run/checkpoint 或确认边界。
- 未实现入口只写边界说明，不放可执行教程。
- CLI 树新增命令时，README、接口树、测试和相关 Flow 页面要同步更新。
