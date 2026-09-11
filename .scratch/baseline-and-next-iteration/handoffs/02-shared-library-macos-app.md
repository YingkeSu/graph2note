# Handoff — issue 02：统一文档库配置并验收 macOS 应用

Branch: `ao/graph2note-10/02-shared-library-macos-app`
Worktree: `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-10`（基于 main `19a3c9e`）

## 完成了什么

建立 Web / CLI / macOS 三入口共用的显式配置优先级，并完成桌面应用构建与启动验收。无产品功能扩展。

1. **统一配置模块**（`graph2note/config.py`，新增）：
   - `support_dir()`：`GRAPH2NOTE_APP_SUPPORT` > `~/Library/Application Support/Graph2Note`（非 macOS 为 `~/.local/share/Graph2Note`）。
   - `resolve_storage_dir(explicit)`：显式参数 > `GRAPH2NOTE_STORAGE` > `<support>/storage`。
   - `resolve_settings_file(storage)`：`GRAPH2NOTE_SETTINGS_FILE` > `<storage>/llm-settings.json`。
   - `ensure_storage_dir(path)`：路径是文件/不可创建时抛可定位的 `ConfigError`（不再裸 `OSError`）。
   - `describe()`：输出 support/storage/settings 供「确认当前位置」。
2. **Web**（`graph2note/webapp.py`）：`create_app` 改走 `config.resolve_storage_dir`/`resolve_settings_file`；新增 `GET /api/config` 返回生效路径；`app.state.storage_dir/settings_path` 暴露。
3. **CLI**（`graph2note/cli.py`）：`notes-export --storage` 默认改为 None，经 `config` 解析并打印 `storage=…`；新增 `graph2note config [--json]` 子命令显示生效配置。
4. **macOS**（`macos/launcher.py`）：`_support_dir` 复用 `config.support_dir()`；移除硬编码 `GRAPH2NOTE_STORAGE` setdefault（改由 config 默认）；保留 `GRAPH2NOTE_SETTINGS_FILE=support/llm-settings.json`（不隐藏已有设置）；启动日志新增 `storage=… settings=…` 定位行（不含凭证）。
5. **文档**：`docs/setup.md`（统一优先级表、旧目录迁移方法、`graph2note config`）、`docs/macos-app.md`（support 目录结构、日志定位行、旧目录沿用说明）。
6. **测试**：`tests/test_config.py` 13 例——support/storage/settings 优先级、env 覆盖、file/不可创建路径报错、`/api/config`、Web 入库→CLI 导出→同配置重载（identity 一致）。

## 如何运行测试

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-10
uv sync --all-extras
uv run pytest            # 404 passed, 0 failed, 0 skipped
```

## 验收证据（逐条 AC）

- **AC1 同一套优先级 + 各入口可确认位置 + 文档**：`config.py` 单点解析；`graph2note config --json`、`GET /api/config`、`launcher.log` 的 `storage=… settings=…` 三入口均输出一致路径；`docs/setup.md` §「文档库配置（统一）」写明默认目录与旧目录（`./.g2n-storage`、`./storage`）的沿用方法（`GRAPH2NOTE_STORAGE`/`--storage`）。
- **AC2 临时目录 Web 入库→CLI 导出→同配置重载**：`tests/test_config.py::test_web_to_cli_to_reload_roundtrip`（隔离 `GRAPH2NOTE_APP_SUPPORT`，create_app 建文档 → `run_incremental_export` 导出到 vault → 再次 create_app 仍见同一 `doc-shared`）。
- **AC3 macOS 构建/启动/退出/重启持久化（隔离 support）**：`./scripts/build_macos_app.sh` exit 0 → `dist/Graph2Note.app`；`GRAPH2NOTE_APP_SUPPORT=/tmp/g2n_i02_support` 启动 → `launcher.log` 记录 `storage=/tmp/g2n_i02_support/storage settings=/tmp/g2n_i02_support/llm-settings.json`；PUT `/api/llm/settings` + seed 文档 → 退出 → 重启 → 文档「隔离验收文档」与 `parse_visual=deepseek/deepseek-v4-flash-vision-exp` 均持久。
- **AC4 错误可定位 + 日志不泄露凭证**：`ensure_storage_dir` 对「路径是文件」「不可创建」抛 `ConfigError`（`test_ensure_storage_dir_rejects_*`）；launcher 仅记录路径，不读/不打印 `.env` 值（`_read_env_file` 只 setdefault）。
- **AC5 macOS 记录与安装文档一致 + 不操作用户真实库**：验收全程用 `/tmp/g2n_i02_support`；真实库 `~/Library/Application Support/Graph2Note/storage` 仍为 **43 篇**（验收前后未变），真实 `launcher.log` 未被本次运行写入。

## 决策与对 spec 的偏离

- **默认 storage 改为 `<support>/storage`**：此前 Web 默认 `./.g2n-storage`、CLI 默认 `./storage`、macOS 默认 Application Support，三处不一致。统一为 Application Support 路径（个人本地应用的规范位置）；旧目录不搬移、不覆盖、不隐藏，沿用方式写入文档（符合「明确切换与沿用旧路径」）。
- **settings 仍随 storage**（`<storage>/llm-settings.json`），macOS 通过 `GRAPH2NOTE_SETTINGS_FILE=support/llm-settings.json` 保持既有位置——避免把用户已有 `support/llm-settings.json` 隐藏，同时不破坏 `test_llm_settings.py` 以 `storage_dir=tmp` 隔离写入的既有约定。
- **未做自动迁移**：不把旧目录数据搬进新默认目录（spec 明确禁止移动/覆盖）。

## 未尽事项 / 给接力者

- macOS 窗口真实 UI 点击（三栏、导出按钮）仍为手工路径；本 issue 只验证后端 + 启动/退出/重启与持久化。
- `Graph2Note.app` 打包产物 `dist/`、`build/` 已被 `.gitignore` 忽略（本地产物，不入库）。
- issue 03（干净基线）会统一收集各 worker 的 handoff 并归档 `.scratch/`；本分支**未提交** `.scratch/baseline-and-next-iteration/` 下的 Status/handoff 变更（延续 issue 01 的「.scratch 不随分支提交」约定）。

## Suggested skills

- `diagnose`：若三入口出现「同一 GRAPH2NOTE_STORAGE 但位置不一致」类问题，用于定位 config 优先级回归。
- 本 issue 纯 Python + pytest，无 UI 设计；`impeccable`/`prototype` 不适用。
