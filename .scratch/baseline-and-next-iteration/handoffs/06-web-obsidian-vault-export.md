# Handoff — baseline issue 06：从 Web 导出 Obsidian Vault

**Status: in-review** · Worker：graph2note-11 · Branch：`ao/graph2note-11/root`
**Verified:** 全离线（注入 golden router + 临时目录 fixture，零网络）· 全量 `pytest`：**360 passed**（跑法见 §3）

## 一句话

Web 新增「导出 Vault」入口：用户在页面填写本机目标目录，后端用**当前文档库**（`app.state.store`）跑
现有增量导出闭环（规则分类 → 持久化 topics → 增量导出），复用用户编辑/改名保护，单向导出、不双向同步。

## 1. 核心交付

| 文件 | 变更 |
|---|---|
| `graph2note/webapp.py` | 新增 `POST /api/vault/export`（发起）+ `GET /api/vault/export`（状态轮询）+ `_run_vault_export` 后台线程 + `_ensure_writable_dir`（建目录 + 探针写入验证可写）+ `app.state.vault_export{,_lock}` 单飞状态。 |
| `graph2note/webstatic/index.html` | 顶栏新增「导出 Vault」导航 + `vault-export-zone`（目标目录输入、导出按钮、状态区、单向导出说明）。 |
| `graph2note/webstatic/app.js` | `#vault-export` 路由 + `renderVaultExport`/`startVaultExport`/`scheduleVaultPoll`/`renderVaultResult`；轮询至 done/failed，展示增量报告（新增/更新/无变化/冲突/删除/保留）。 |
| `graph2note/webstatic/style.css` | `.vault-export-*` 样式（复用 `.btn/.dim/.hidden` 等既有 token）。 |
| `graph2note/notes/exporter.py` | **修一个阻塞 bug**：`_safe_name` 原先把 `-` 换成 `_`，与渲染层确定性资产名 `assets/<doc>-diagram-<n>.png` 不一致 → 导出死链。现保留 `-`（详见 §2 决策）。 |
| `tests/test_webapp_vault_export.py` | 新增 7 个离线集成测试（见 §3 AC 对照）。 |

### 导出状态机（单飞，避免「处理中重复发起」）
```
POST /api/vault/export {target_dir}
  → 空目标 422 | 进行中 409 | 空库 {"status":"empty"} | 目标不可写 422
  → 置 running、起后台线程 → {"status":"running"}
GET /api/vault/export → idle|running|done|failed（done 带 report + vault_root + exported_documents）
```
失败只会落到 `failed`（带 `error`），**永不**把失败展示为成功。

## 2. Key decisions

- **目标目录 = 服务端本机路径（文本框输入）**：应用只 bind 127.0.0.1，浏览器与服务端同机；首版不引入原生目录选择器。`_ensure_writable_dir` 用「建目录 + 写探针文件再删」验证可写，失败给 `目标目录不可用/不可写` 可解释错误。
- **复用而非重写**：直接调 `graph2note.notes.loop.run_incremental_export(store, target)`——规则分类 + `apply_scheme` 持久化 topics + `export_incremental`（document_id 锚 diff + 指纹判「旧系统文件 vs 用户编辑」+ 冲突改名保留双方 + 死链校验）。Web 与 CLI `notes-export` 同一路径。
- **单向导出语义**：UI 文案明确「单向导出，不会把 Vault 里的修改同步回 graph2note」，按钮为「导出到 Vault」，不出现「同步」。
- **`_safe_name` 保留 `-`**：附件名来自 `FileAssetWriter._path`（`assets/<doc>-diagram-<n>.png`，含连字符）。`_safe_name` 原先把 `-` 归入「非字词」而替换为 `_`，但 note 正文引用保持原名 → 死链 → 导出失败。改为 `re.sub(r"[^\w.-]+", "_", …)` 仅替换真正不安全的字符（空白/路径分隔符等），与渲染层命名一致。MOC/集合/主题名也用同一函数，内部一致（MOC 链接用的是 `e.safe_id`，本就保留 `-`），现有 notes-organizer 测试不受影响。
- **空库是独立状态而非错误**：`POST` 直接返回 `{"status":"empty"}`（200），前端显示「文档库为空」，不当作失败。

## 3. 验证

```bash
# 全量离线（带本地 API key 占位即可——9 个「离线 seeded cache」测试在 load_api_key 之后才查缓存，
# 无 key 会回退 live 报错；主检出的 .env 即此作用，本 worktree 无 .env，故用 env 占位跑）
OPENCODE_API_KEY=dummy DEEPSEEK_API_KEY=dummy KIMI_API_KEY=dummy python3 -m pytest -q
# → 360 passed（本 worktree 无 .env；主检出 .env 存在时直接 python3 -m pytest 即为同结果）

python3 -m pytest tests/test_webapp_vault_export.py -q   # 7 passed（全离线）
```

**AC 逐条对照**

| AC | 证据 |
|---|---|
| Web 发起→后端执行→结果展示；导出当前文档库；目标规则明确、错误可解释 | `test_vault_export_end_to_end`（POST→轮询→done + vault_root + report）；`test_vault_export_empty_library`；`test_vault_export_unwritable_target`（422「不可用/不可写」）；后端用 `app.state.store`（当前库，不硬编码路径） |
| 含 Markdown/原稿/附件/时间/标签/集合元数据/MOC；来源链接与附件可解析 | `test_vault_export_end_to_end` 断言 note.md frontmatter（`document_id/source_image/parsed_at/exported_at/topics/tags/collections/import_time`）+ `source.*` 原稿 + `assets/*` 附件 + `mocs/*.md`；死链由 exporter `_validate_all_links` 兜底（失败即 `failed`）；`_safe_name` 修复后渲染层 `-diagram-` 资产名不再死链 |
| 空库/目标不可写/重复发起/失败均有明确状态；失败不显示为成功 | `test_vault_export_empty_library`（empty）· `test_vault_export_unwritable_target`（422 + 状态回 idle）· `test_vault_export_duplicate_in_progress`（409「进行中」）· `test_vault_export_failure_not_success`（failed + error，`!= done`） |
| 保持增量与用户修改保护；「导出」语义不暗示双向同步 | `test_vault_export_second_run_unchanged`（二次导出 `added/updated==[]`、`unchanged` 非空、manifest 逐字节不变——零写入）；用户编辑保护复用 `export_incremental`（notes-organizer issue 03 已测）；UI 文案单向 |
| API/浏览器集成 + 独立 fixture Vault 验证；Obsidian 打开样例；不改真实 Vault | 全部 API 集成测试跑在临时目录 fixture（不触碰真实 Vault）；`test_vault_export_ui_present`（首页含 `vault-export-zone`、app.js 含 `startVaultExport`）；**Obsidian 桌面打开验证为人工步骤**（见下） |

**人工验证（Obsidian 桌面，无法在 CI 自动化）**：启动 Web（`python3 -m uvicorn graph2note.webapp:create_app --factory` 或既有启动方式）→
上传一张手稿 → 顶栏「导出 Vault」填 `/tmp/g2n-vault` → 导出完成 → 用 Obsidian「打开文件夹作为 Vault」指向该目录，核对：笔记 frontmatter、正文首部原稿图、`assets/` 附图、`mocs/` 导航链接均可打开。

## 4. 已知限制 / 后续

- **目录选择是文本框**，非原生目录选择器（本地单用户首版够用；要更顺滑需引入目录浏览端点，属后续）。
- **冲突明细展示留 issue 07**：本 issue 只在导出结果里显示各分类计数；逐文件冲突位置与两份内容对照由 07 做。
- **文档库默认目录统一（Web `.g2n-storage` vs CLI `storage`）不在本 issue**：后端直接用 Web 实际在用的 `app.state.store`，因此「导出的是当前文档库」天然成立；统一配置属 issue 02。
- **Obsidian 桌面打开验证**是人工步骤，本交付以 fixture 目录树 + 链接校验 + API 集成替代自动断言。
- **无密钥提交**：未改动任何密钥读取；测试仅用 `dummy` 占位 key 满足离线 seeded-cache 测试在 `load_api_key` 之后的缓存命中路径，零网络。

## 5. 对派发的提醒（环境相关，非本 issue 缺陷）

本 worktree 无 `.env`（gitignored，未随 worktree 拷贝）。干净环境直接 `pytest` 会有 9 个**离线 seeded-cache** 测试失败（`test_cli_parse`/`test_e2e_images`/`test_issue11_parse`/`test_pipeline`），根因是这些测试的缓存命中发生在 `load_api_key()` 之后，无 key 即回退 live 报 `未找到 OPENCODE_API_KEY`；设任意占位 key（或复刻主检出 `.env`）即全部离线通过（360 passed）。这是 03 网关改造引入的「load_api_key 先于缓存查询」顺序，属 03 领地，本 issue 未触碰。

## suggested skills

- 接手 issue 07（冲突明细展示）继续用 `report.conflicts/conflict_backups` 渲染 UI。
- 若做目录选择器，参考 `impeccable` 做表单 UX；`prototype` 可先探目录浏览交互。
