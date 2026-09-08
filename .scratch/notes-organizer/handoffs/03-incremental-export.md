# Handoff — notes-organizer Issue 03：增量导出闭环（幂等、不覆盖用户修改）

**Status: in-review** · Track A worker：graph2note-2 · Branch：`dev/no03-incremental-export`
**Verified:** 全离线 · 全套 `pytest`：**217 passed / 2 skipped**（+10 增量测试）

---

## 1. 核心交付

在已有导出链（01 纯函数导出器 + 02 分类/MOC + set_topics）上新增增量闭环，无新增依赖。

| file | change |
|---|---|
| `graph2note/notes/exporter.py` | 新增 **`render_vault_files()`**（单一确定性渲染：`{相对路径: bytes}`，全量与增量共用 → 保证增量结果与全量**内容等价**）；`export_vault` 重构为基于 render 的全量覆盖；新增 **`export_incremental()`**（增量 diff 应用）；manifest 新增 **`fingerprints`**（每个系统文件 sha256），供下次增量判别“旧系统文件 vs 用户编辑文件”；`_write/_read_bytes/_bhash/_conflict_name/_prune_empty_dirs` 工具。 |
| `graph2note/notes/loop.py`（新） | **`run_incremental_export(store, out_dir, __classify=…)`** — 闭环函数：`load_entries → classify → apply_scheme(持久化 topics) → 重新 load → export_incremental`。一条路径演示“解析新文档→分类→增量导出→vault 反映变化”。 |
| `graph2note/cli.py` | 新增 `graph2note notes-export -o <vault> --storage <lib>` 子命令（调 loop），打印 documents/report 汇总，幂等可重跑。 |

### 增量 diff 语义（document_id 为锚 + 内容指纹）
对每个期望系统文件，按磁盘状态分派：
- **缺失** → 写入（`added`）
- **逐字节相同** → 不动（`unchanged`，mtime 稳定）
- **不同但 == 上次指纹** → 旧系统文件 → 覆盖刷新（`updated`）
- **不同且 ≠ 上次指纹** → **用户编辑过** → 改名保留用户版 + 写我们的版本（`conflicts`，报告列出 `conflict_backups`），双方共存
- **上次有、本次无** 的系统文件：磁盘仍匹配上次指纹才删除（`deleted`）；被用户改过/改名的**不删**（`kept_user`）；随后空目录剪枝。

`exported_at` 仍确定性（显式参数或输入 max updated_at，非墙钟），manifest 内容不变则不重写（真正的零写入）。

## 2. Key decisions

- **共享渲染单一来源**：`render_vault_files` 是全量与增量的唯一渲染函数，因此“增量结果与全量导出内容等价（同一 manifest 口径）”由构造保证，测试逐字节比对验证。
- **指纹识别“旧系统文件 vs 用户编辑”**：manifest 记录每个系统文件 sha256。磁盘文件 hash == 上次指纹 ⇒ 是我们生成过的旧文件（覆盖/删除安全）；否则是用户内容（绝不覆盖/删除）。这是“不覆盖用户修改 + 改名不被误删”的判别依据。
- **用户改名保护**：用户把 `note.md` 改名（Obsidian 常见）→ 旧路径文件缺失，我们只回填受管理路径（`added`）；用户自建文件（如 `My Essay.md`）不进 manifest、不在删除遍历范围，原样保留。AC“改名的文件不被当作已删除而清理”覆盖。
- **冲突文件改名保留双方**：`note.md.user-<hash>`（确定性唯一），用户版本完整保留，报告列出新旧路径。
- **零写入**：无变化时无文件改写（mtime 稳定，Obsidian 同步友好）；manifest 同内容不重写。
- **死链校验全程**：增量完成后 `_validate_all_links` 照常跑，MOC/笔记/附件任一处死链即抛 `VaultExportError`。

## 3. 验证

```bash
python3 -m pytest tests/test_incremental_export.py -q   # 10 passed（全离线）
python3 -m pytest -q                                     # 217 passed / 2 skipped（全套）
python3 -m graph2note notes-export -o /tmp/vault --storage <lib>
# 再跑一遍（无变化）→ 0 写入；手改 note.md 再跑 → conflicts + backup；删记录再跑 → deleted + 空目录清理
```

覆盖 AC：新增/更新/删除文档增量落地（`test_add_new_document`/`test_update_document`/`test_delete_document`）；用户编辑不被覆盖、改名保留双方且报告列出（`test_user_edit_not_overwritten`/`test_user_renamed_file_not_deleted`）；MOC 随增量与笔记集一致（无死链无遗漏，`test_moc_matches_docs_after_remove_and_add`）；连续两次无变化零写入（mtime 稳定，`test_no_change_export_is_zero_write`）；增量与全量逐字节等价（`test_incremental_equals_full_export_content`）；闭环 load→classify→persist→export（`test_closed_loop_reclassify_incremental`）与 CLI 幂等重跑（`test_cli_notes_export`）。以上全部在临时目录集成、离线。

## 4. 已知限制 / 后续

- **删除语义为“清理或标记”**：对系统生成物安全删除（匹配上次指纹）；如用户动过该文档目录下的文件则保留（`kept_user`），由报告提示，不做破坏性删除。
- **冲突备份不带拓扑改名**：用户编辑的笔记改名保留在同目录（内部相对链接仍有效）。
- **MOC 是系统生成物**：始终随增量重建可覆盖；用户对 MOC 的手改同样走冲突改名保留。
- **分类/增量是手动触发**：无定时自动整理（PRD out of scope）；`notes-export` 每次全栈重分类（<20 篇规则分类即时）。
- **无密钥提交**：运行时才读 `OPENCODE_API_KEY`；无 `.env` 入库。

## 5. 手工冒烟（一次性，本机）

```bash
# 已有若干 DocumentRecord 后：
python3 -m graph2note notes-export -o /tmp/vault --storage storage   # 首导
python3 -m graph2note notes-export -o /tmp/vault --storage storage   # 无变化 → 0 写入
# Obsidian 里手改 notes/<id>/note.md 再跑一次 → 报告 conflicts，生成 note.md.user-<hash> 保留你的版本
# 删除某文档记录再跑 → 对应 notes/<id>/ 系统文件 removed、mocs 更新
```