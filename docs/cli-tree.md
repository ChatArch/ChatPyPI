# CLI 能力地图

当前命令树包含已实现路径和规划入口。未实现命令必须保持非 0 退出或明确 checkpoint，不应被自动化误判为成功。

```text
chatpypi
├── init / build / check / upload / probe        # legacy shortcut
├── pkg
│   ├── init
│   ├── build
│   ├── check
│   ├── upload
│   └── probe
├── auth
│   ├── login
│   ├── whoami
│   └── session
│       ├── show
│       └── clear
├── profile
├── config
├── project
│   └── list
├── publisher
│   ├── list
│   ├── detail
│   ├── add-github
│   ├── pending-list
│   ├── pending-add
│   └── pending-remove
├── token
│   └── create          # 未实现 / checkpoint
├── doctor
│   └── check           # 未实现 / checkpoint
└── docs
    ├── links
    ├── examples
    └── open
```

## 文档更新规则

- 每个已实现命令都要能追到 Python 函数或 service 层。
- 如果命令会写远端状态，文档必须说明凭据、权限、dry-run/checkpoint 或确认边界。
- 未实现入口只放路线图，不放可执行教程。
