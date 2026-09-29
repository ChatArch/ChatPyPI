# uv / pip 用户下载源

`chatpypi mirror` 只管理**当前用户**的 uv 与 pip 默认下载索引。它与 ChatUp alias、PyPI 登录、Publisher、上传仓库、`.pypirc`、代理和 shell 配置完全分离。

## 命令

```bash
chatpypi mirror show [--tool uv|pip|all] [--format text|json]
chatpypi mirror set [default|tsinghua] [--tool uv|pip|all] [--dry-run] [-i|-I] [--format text|json]
```

`--tool` 默认是 `all`。`default` 写入 `https://pypi.org/simple`，`tsinghua` 写入 `https://pypi.tuna.tsinghua.edu.cn/simple`。缺少 preset 时仅在允许且有 TTY 时通过 ChatStyle 提示；`-I` 始终非交互并快速失败。建议先运行 `--dry-run`，它不会创建文件或目录。

```bash
chatpypi mirror show
chatpypi mirror set tsinghua --dry-run
chatpypi mirror set tsinghua -I --format json
chatpypi mirror set default --tool pip -I
```

## 原生用户文件

ChatPyPI 写入工具自己读取的原生用户配置，不维护私有镜像状态：

| 工具 / 系统 | 当前用户目标 |
| --- | --- |
| uv，Linux / macOS | `$XDG_CONFIG_HOME/uv/uv.toml`，未设置时 `~/.config/uv/uv.toml` |
| uv，Windows | `%APPDATA%\\uv\\uv.toml` |
| pip，Linux | `$XDG_CONFIG_HOME/pip/pip.conf`，未设置时 `~/.config/pip/pip.conf` |
| pip，macOS | 按 pip 原生规则选择已有的 `$XDG_DATA_HOME/pip`、`~/Library/Application Support/pip`，否则 `~/.config/pip/pip.conf` |
| pip，Windows | `%APPDATA%\\pip\\pip.ini` |

uv 使用现代 `[[index]]`、`url`、`default = true`，并通过 `tomlkit` 保留无关选项、注释和其它索引。已知的 official/Tsinghua `index-url`、`default-index` 或 `[pip].index-url` 会安全迁移；自定义 legacy 值、自定义 default index、需要改指向的命名 default index 或多个 default index 会在写入前拒绝，避免改写私有认证或索引优先级。

pip 只设置当前文件的 `[global] index-url`，保留其它 section 和 option；使用标准 INI 解析器重写，支持冒号、下划线别名和多行旧值，注释与排版可能被规范化。legacy 用户文件仍会被读取和校验；当前用户文件按 pip 原生优先级覆盖 legacy 值。命令不会改 system/site（包括 active venv）配置，也不会改命令专属 section；这些更高或更具体的设置仍可能覆盖用户默认值。

## 状态与安全边界

`show` 明确报告 `USER configuration`，不是全局或最终 effective 配置。未知/自定义 URL 始终显示为 `custom / REDACTED`。以下相关环境变量存在时，只报告变量名而不显示值：

- uv：`UV_DEFAULT_INDEX`、`UV_INDEX_URL`、`UV_CONFIG_FILE`、`UV_INDEX`、`UV_EXTRA_INDEX_URL`
- pip：`PIP_INDEX_URL`、`PIP_CONFIG_FILE`、`PIP_EXTRA_INDEX_URL`

环境变量、命令行参数、uv 项目配置、pip site/命令专属配置仍可能覆盖用户文件；ChatPyPI 不清理环境变量，也不会声称子进程能修改父 shell。

写入前会解析所有请求的配置，拒绝目标 leaf symlink，使用同目录私有临时文件与 atomic replace，并保留已有文件 mode。`--tool all` 的第二个目标失败时会回滚第一个目标；回滚本身失败会给出明确的固定错误。错误和状态不会包含原始自定义 URL。

## Python API

```python
from chatpypi.mirror_ops import resolve_user_config_paths, set_mirrors, show_mirrors

paths = resolve_user_config_paths()
preview = set_mirrors("tsinghua", tool="all", dry_run=True)
status = show_mirrors(tool="all")
```

`resolve_user_config_paths()`、`set_mirrors()` 和 `show_mirrors()` 支持注入 `home`、`platform`、`env` 和显式路径，便于在隔离环境中验证而不触碰开发者配置。
