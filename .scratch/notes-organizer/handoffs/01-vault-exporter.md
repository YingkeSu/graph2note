# Handoff — notes-organizer Issue 01：Obsidian Vault 导出器（含溯源）

**Status: in-review** · Track A worker：graph2note-2 · Branch：`dev/no01-vault-exporter`
**Verified:** 全离线（fixture + 注入 hash，零网络）· 全套 `pytest`：**168 passed / 2 skipped**

---

## 1. 核心交付

新增包 **`graph2note/notes/`**（notes-organizer feature，独立于主管线）：

| module | role |
|---|---|
| `exporter.py` | **纯函数导出器**：`ExportEntry[] + out_dir → Obsidian vault 文件树`；`Vault` 值对象、链接校验、死链即抛 `VaultExportError`。实现：每文档一篇笔记、frontmatter 溯源、原图嵌入、附件落位、`dedupe_documents()` 同源去重、确定性 `exported_at`。 |
| `loader.py` | 薄接缝：`DocumentStore（issue 07）→ ExportEntry[]`，只读取每个记录的**最新版**；调用 dedupe。 |

### 产出 vault 树
```
<out>/
  notes/<safe_document_id>/
    note.md              # frontmatter + 正文首部原图嵌入 + 识别正文
    source.<ext>         # 原始手稿图片（溯源）副本
    assets/<name>        # 附件副本（引用保持相对有效）
  export-manifest.json   # 确定性清单（exported_at / documents / 路径索引）
```

### frontmatter 溯源字段（AC 必含项）
```yaml
---
document_id: <id>
title: <title>
source_image: source.<ext>          # vault 内相对原图（正文首部嵌入同一路径）
source_original_path: <系统原图绝对路径>  # 定位回系统 DocumentRecord
parsed_at: <最新版解析时间>
exported_at: <确定性时间，非墙钟>
topics: [ ... ]                      # 分类 seam 之前为 []，键始终存在
---
![<title> 原稿](source.<ext>)
<识别正文>
```

### 溯源两步到位
- 正文首部以**相对路径**嵌入原图（`![...](source.<ext>)`，叠放在 `note.md` 旁的 `source.<ext>` 副本）→ Obsidian 内对照原稿。
- `document_id` + `source_original_path` → 可定位回系统内 DocumentRecord（继续编辑/重解析）。

## 2. 同源去重口径（写入 key decision）

采用**双口径、`dedupe_documents()` 统一**：

1. **记录内（版本链）——主口径**：`loader` 每个 DocumentRecord 只导出其 `current_markdown` + 最新版的 `preprocessed/assets`。issue 07 的 reparse 是更新同一记录并追加版本，因此“同源重复解析只导出最新版”在记录内由版本链天然满足——vault 永远只看到最新版，绝不出现旧版残留。依赖 07 的版本链（稳定 `document_id` 合并为版本）。
2. **记录间（09 pHash 聚类）——补充口径**：同一物理页若因不同上传/跨 PDF 而成为**多条** DocumentRecord，用 09 的 `ingest.hash.phash`（DCT-II pHash，光照鲁棒）对每记录最新版 preprocessed 图（缺图回落 original）算感知哈希，按 `hamming ≤ threshold`（默认 6，与 ingest 引擎一致）并查集聚类，保 **`updated_at` 最新**者为代表。`hash_of` 可注入（离线测试用确定性假 hex hash）。

> 最稳口径判断：**以 07 版本链为主**（重解析本就不该跨记录），**09 pHash 兜底记录间合并**。这样既不用在导出器里猜测“哪两次解析应算同一页”的时序，又能消费 09 已证的页级感知哈希判据跨记录去重。该口径写入本 handoff §2 与代码 docstring。

## 3. 确定性 / 幂等

- `exported_at` **绝不取墙钟**：显式参数指定，否则取输入记录 `updated_at` 的**最大值**（对同一输入恒定）。两次导出同输入 → 逐字节一致。
- 文件名全由 `document_id` 派生（`safe_id`），笔记/附件/清单路径确定 → 稳定。
- **幂等测试**：两次导出到两个临时目录，递归逐文件 `read_bytes()` 相等。

## 4. 链接有效性校验（死链即失败）

`export_vault()` 写完整个 tree 后，对每篇笔记收集相对引用（标准 `![alt](rel)` / `[link](rel)` / wiki `[[file]]`，跳过 `http(s)://` 与锚点），相对笔记目录解析，任一目标不存在即抛 `VaultExportError` 并列出死链。全 vault（笔记 ↔ 原图 ↔ 附件）覆盖。

## 5. 验证

```bash
python3 -m pytest tests/test_vault_exporter.py -q   # 10 passed（全部离线）
python3 -m pytest -q                                 # 168 passed / 2 skipped（全套）
```

覆盖 AC：fixture 快照（目录树/frontmatter/附件落位）、frontmatter 溯源字段齐全 + `source_original_path` 回链系统记录、原图嵌入与附件引用可达（死链抛错）、同源去重只留最新、真实（小规模）`FileDocumentStore` 导出到临时目录集成、reparse 同记录不重复（latest 获胜）、幂等逐字节一致、`exported_at` 确定性。

## 6. 已知限制 / 后续

- **topics 目前为空**：分类（主题归纳/MOC/文件夹）为后续 issue；`DocumentRecord` 尚未落盘 `topics`（分类 seam 产出后写入记录，`loader` 已读取 `rec["topics"]`，届时自动带上）。本次 frontmatter 恒含 `topics` 键（可为 `[]`），满足 AC“必含”。
- **增量/不覆盖用户编辑**（User Story 6）：issue 01 AC 未要求，且与幂等目标冲突，故导出 = 全量覆盖系统生成文件；增量 diff 及“不覆盖改名/手工编辑文件”留给后续 issue（以 document_id 为锚）。
- **MOC / 文件夹分类**：分类 seam 未实现（PRD User Story 2/3），非 01 范围。
- **导出去重不重渲染**：仅消费已解析记录与图片，不回写主管线。
- **无密钥/无外部依赖**：仅 `PIL`（00 已有）+ `ingest.hash.phash`。

## 7. 手工冒烟（一次性，本机）

```bash
GRAPH2NOTE_STORAGE=/tmp/nostore python3 -m pytest tests/test_documents.py::test_...(或直接)
# 或经 webapp 建几份记录后用:
python3 -c "from graph2note.store import FileDocumentStore;import graph2note.notes.loader as L, graph2note.notes.exporter as X; s=FileDocumentStore('/tmp/nostore'); E=L.load_entries(s); X.export_vault(E,'/tmp/vault'); print('ok')"
# 再开 Obsidian 指向 /tmp/vault 验证：frontmatter、原图嵌入、附件、清单。
```