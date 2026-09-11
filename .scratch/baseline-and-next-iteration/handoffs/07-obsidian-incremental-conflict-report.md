# Handoff — baseline issue 07：展示 Obsidian 增量变化与冲突结果

**Status: in-review** · Worker：graph2note-11 · Branch：`ao/graph2note-11/root`
**Verified:** 全离线（注入 golden router + 临时目录 fixture，零网络）· 全量 `pytest`：**399 passed**（跑法见 §3）

## 一句话

在 06 的 Web 导出链路上，把增量导出报告从「分类计数」升级为「逐文件明细 + 冲突双路径 + 用户文件定位」，
并在 UI 明确「保留用户备份并生成系统版本（未自动合并）」；后端区分失败 vs 部分完成，报告带 task_id 不混用。

## 1. 核心交付

| 文件 | 变更 |
|---|---|
| `graph2note/webapp.py` | ① `_enrich_export_report()` 把原始增量报告转成 UI-ready：`conflicts=[{managed,backup}]`（完整 vault 相对路径）、`user_files`（扫描 notes/mocs/collections 中非受管文件——用户改名/自建文件可定位）。② `_dir_fingerprint()` 在失败时判断是否已写入部分文件 → `partial` 标记。③ 每次导出带 `task_id`（uuid），POST/GET 状态与报告均携带，前端据此不混用任务。④ **修 bug**：空库 `POST` 此前不重置状态，`GET` 会返回上一次 run 的 stale `done` 报告——现空库时清零状态。 |
| `graph2note/webstatic/app.js` | `renderVaultResult` 渲染逐分类 `<details>` 文件列表 + 冲突区（受管输出 vs 用户备份双路径 + 未自动合并文案）+ 部分完成提示；`scheduleVaultPoll` 按 `task_id` 过滤，不把旧任务报告当新结果。 |
| `graph2note/webstatic/style.css` | `.vault-conflicts` / `.vault-files` / `code` 明细样式。 |
| `tests/test_webapp_vault_export.py` | 新增 8 个离线测试（见 §3 AC 对照）。 |

### 报告结构（POST/GET `/api/vault/export` 的 `report`）
```json
{
  "task_id": "…", "exported_at": "…",
  "added": ["notes/doc-x/note.md", …],
  "updated": ["…"], "deleted": ["…"], "unchanged": ["…"],
  "conflicts": [{"managed": "notes/doc-x/note.md", "backup": "notes/doc-x/note.md.user-<hash>"}],
  "kept_user": ["…"],
  "user_files": ["notes/doc-x/My Essay.md", …]
}
```

## 2. Key decisions

- **冲突双路径**：原始 `conflict_backups` 只给备份文件名，`_enrich_export_report` 补全为 vault 相对路径（备份与受管文件同目录），UI 同时展示两处位置供核对，文案明确「未自动合并」。
- **用户文件定位**：`user_files` = 扫描 `notes/mocs/collections` 下不在 `vault.all_files`（受管集）的文件——覆盖「用户改名」与「上次冲突留下的 `.user-<hash>` 备份」两类，满足 AC「结果中能定位这些文件」；也是「重试不掩盖已发生冲突」的可见化（重跑后旧备份仍在 user_files 中）。
- **partial 判定**：`_dir_fingerprint(target)`（相对路径+size 快照）在 `run_incremental_export` 前后比对；失败时若已写入/改写文件 → `failed + partial: true`，否则 `partial: false`。exporter 是先写文件后做死链校验，故「死链失败」通常即 partial。
- **task_id 单飞隔离**：POST 生成 task_id，前端 poll 时若返回 `task_id` 与本次发起不一致则忽略，杜绝「不同任务报告混用」。后端仍保持单飞锁（409）。
- **复用不重写**：仍走 `graph2note.notes.loop.run_incremental_export`（规则分类 + 增量 + 用户编辑/改名保护），本 issue 只改「展示层 + 状态语义」，未碰增量 diff 逻辑。

## 3. 验证

```bash
# 全量离线（带本地 API key 占位即可，原因见 issue 06 handoff §5）
OPENCODE_API_KEY=dummy DEEPSEEK_API_KEY=dummy KIMI_API_KEY=dummy python3 -m pytest -q
# → 399 passed

python3 -m pytest tests/test_webapp_vault_export.py -q   # 15 passed（06 的 7 + 07 的 8，全离线）
```

**AC 逐条对照**

| AC | 证据 |
|---|---|
| 首次/无变化重跑/改内容/改元数据/删文档 → 返回与落盘一致的分类明细 | `test_report_first_export_task_id_and_added`（added 全量）· `test_report_no_change_reprun_zero_write`（unchanged + **mtime 逐文件不变**）· `test_report_content_change_marks_updated`（save_edits → updated + 正文变化落盘）· `test_report_metadata_change_marks_updated`（set_tags → updated + frontmatter 变化）· `test_report_delete_document_marks_deleted`（删 1/2 → deleted + vault 只剩 1 篇） |
| 无变化重跑不改写文件；用户编辑/改名文件保留且可定位 | `test_report_no_change_reprun_zero_write`（mtime 稳定）· `test_report_user_edit_conflict_locatable`（managed + backup 双路径都在盘上、备份含用户内容、受管文件不含）· `test_report_user_rename_preserved_and_locatable`（`user_files` 列出 `My Essay.md`、受管 note.md 回填） |
| UI 明确「保留用户备份并生成系统版本」，不描述为自动合并 | `app.js` `vaultConflictsHtml` 文案「已保留为备份并同时生成系统版本（未自动合并）」；`test_vault_export_ui_present`（06）+ app.js 含 `vaultConflictsHtml` |
| 失败/部分完成区别显示；不混用任务报告；重试不掩盖冲突 | `test_report_failure_partial_vs_clean`（写文件后抛错 → `partial:true`；未写即抛 → `partial:false`）；`task_id` 贯穿 POST/GET/report，前端 poll 按 task_id 过滤；重跑后冲突备份仍出现在 `user_files` |
| 离线 e2e 覆盖用户编辑、改名、重跑、来源/附件引用、元数据更新 | 上述 8 测试全部走真实 FileDocumentStore + 临时 vault（来源 `source.*`/附件 `assets/*` 引用由 exporter 死链校验兜底）；`test_report_metadata_change_marks_updated` 覆盖元数据更新 |

**人工验证（Obsidian 桌面，无法 CI 自动化）**：Web 上传 1 篇 → 导出 → 在 Obsidian 里手改 `note.md` → 再导出 → 导出结果区应显示「冲突」+ 受管路径与 `note.md.user-<hash>` 备份路径；在 Obsidian 打开两处核对。改名前/改名场景同理看 `user_files` 列表。

## 4. 已知限制 / 后续

- **冲突不自动语义合并**（首版明确不含）：系统只保留双方，用户在 Obsidian 自行核对/合并。
- **目录选择仍是文本框**（06 延续），非原生目录选择器。
- **`exported_at` 确定性语义**：`=max(updated_at)`，故「改内容」会因 `save_edits` 更新 `updated_at` 而让所有笔记的 `exported_at` 一起变 → 该场景 `updated` 会含全部 note（与落盘一致但信号较宽）；「改元数据（tags/topics）」不更新 `updated_at`，`updated` 只含受影响文件。属 notes-organizer 既有设计，本 issue 不改。
- **无密钥提交**：测试仅用 `dummy` 占位 key；未改动任何密钥读取。

## 5. 环境提醒（继承 06 handoff §5）

本 worktree 无 `.env`；离线 seeded-cache 测试在 `load_api_key()` 之后才查缓存，故干净环境需任意占位 key（或复刻主检出 `.env`）才能全绿。此顺序属 03 网关改造领地，未触碰。

## suggested skills

- 08/09/10/11（PDF 链路）与此无耦合，可独立进行。
- 若后续做目录选择器/更顺滑的冲突核对 UI，参考 `impeccable` 做表单与冲突对比界面。
