# test_chatpypi_mirror

## 目标

验证 `chatpypi mirror` 的公开 CLI 合约，而不读写开发者真实配置：

- `show` / `set` 的 JSON 状态和 USER scope。
- 缺少 preset 时的 ChatStyle 交互，以及 `-I` 的确定性失败。
- `--dry-run` 不创建文件或目录。
- console wrapper 把 `mirror` 识别为真实命令，不改写成 `pkg init`。
- `--tree` 回读 `mirror show|set`。
- pip 和 uv 从隔离的 `HOME` / `XDG_CONFIG_HOME` 读取写入结果。

## 隔离边界

测试只使用 pytest 临时目录，并为子进程设置 process-scoped `HOME`、`CHATARCH_HOME`、`XDG_CONFIG_HOME` 和 `PYTHONPATH=src`。pip 用 `pip config get --user` 回读；uv 用固定的 `/home/zhihong/.local/bin/uv` debug discovery 回读，不访问网络。测试不修改 operator 配置、shell 环境或全局 mirror。
