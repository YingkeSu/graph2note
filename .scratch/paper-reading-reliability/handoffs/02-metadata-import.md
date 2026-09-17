# 02 — 元数据导入接线与历史补提取（handoff）

Status: **in-review**
分支：`dev/prr-02-metadata`（worktree `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138`；基线 main `f771b9d`；本地提交，未 push、未建 PR、未合并 main、未改共享 BOARD）
作者：AO worker `graph2note-138`
日期：2026-09-16

## 结论一句话

论文导入现在会跑既有 P2 确定性解析并写入 P2 元数据槽，阅读页/库卡片/导入结果同源；导入成功与元数据提取结果分开报告；历史论文有逐篇与批量显式补提取入口，幂等、可重试、保留手工字段；文献项保留原文并显示解析状态，绝不伪造 DOI 或库内链接；GROBID 只作为可选的离线可测 seam，缺环境即降级。

## 交付物

| 文件 | 说明 |
|---|---|
| `graph2note/papers/extract.py`（新） | 导入期提取+持久化：`extract_and_persist` / `preferred_document_title` / `merge_manual_meta` / `run_extraction` |
| `graph2note/papers/grobid.py`（新） | 可选 GROBID：纯 TEI→字段解析、可注入 transport、无配置即 `GrobidUnavailable` |
| `graph2note/papers/pipeline.py` | `PaperJob.meta_status/meta_error`；提交后用抽取标题/文本跑 `run_metadata_extraction`；`result_payload` 优先读 P2 槽 |
| `graph2note/papers/enhance.py` | `apply_meta_proposal` 增加 `evidence` / `note_label`（默认值不变，LLM 路径行为不变） |
| `graph2note/webapp.py` | 逐篇/批量补提取端点、GROBID 注入 seam、view 参考文献状态、库卡片读 P2 标题 |
| `graph2note/webstatic/*` | `#paper-reextract` 按钮与状态、参考文献状态标签、上传完成 toast 带元数据状态 |
| `tests/test_papers_meta_import.py`（新，18 例） | 端到端 import→persist→view、手工保护、幂等、批量、失败隔离、Y5 回流、GROBID 离线 |
| `tests/taxonomy.py` | 登记 `test_papers_meta_import` → `ingest` + integration |
| `tests/test_papers_ingest_api.py` / `tests/test_papers_meta_dualslot.py` / `tests/paper_view.mjs` | 更新既有断言以匹配新契约（导入结果含抽取 meta；view 参考文献附 `notes`） |

## 决策与偏离

1. **落点**：遵循 Y2 裁决（双落点）——确定性结果只写 P2 槽（`set_paper_meta` / `set_paper_references`），P1 `paper.json` 继续保留空占位；`result_payload` / view / 库卡片都从 P2 槽读取，从而三方一致。
2. **标题**：导入提交时用抽取标题（`preferred_document_title`，无标题回落文件名），使库卡片/搜索/阅读页从第一次读取就一致。历史论文补提取后，库卡片通过 `_paper_card_fields` 读同一 P2 标题（记录 `title` 本身不改）；阅读页标题本就优先 `meta.title`。
3. **状态分离**：`PaperJob.meta_status`（`ok|empty|failed`）与导入 `status` 独立；提取失败不使导入失败，`meta_error` 记录原因，可重试。
4. **幂等**：notes 用有序去重拼接；同一全文重复提取写出的 P2 槽字节一致。
5. **手工字段**：仅当存储 provenance 的 `source == "manual"` 且值非空时保留，并逐字段标 `manual-preserved:<field>`，整体 `source` 置 `manual`（与 Y1 的 PATCH 写入一致）。
6. **GROBID 证据标注**：不扩展 `MetaSource` 字面量（避免改 SPEC §2 契约），字段来源仍记渠道 `text-layer|vlm`，证据字段标 `grobid:tei`，并加 `grobid-fields:<...>` / `grobid-unavailable:*` note。若维护者希望新增 `grobid` source 枚举，属契约扩展，另行裁决。
7. **未做库内关联回填**：导入不自动 `resolve_references`（逐篇 O(n²) 且属既有独立端点），保持“无证据不伪造链接”。

## 验收证据（可复跑）

```bash
# 全量离线（主仓 .venv，Python 3.13）
/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest -p no:warnings
# → 1386 passed / 0 failed / 0 error / 0 skipped（基线 f771b9d 1368，+18）

# 本 issue 新测试
… -m pytest -p no:warnings tests/test_papers_meta_import.py      # 18 passed
# 相邻契约
… -m pytest -p no:warnings tests/test_papers_ingest.py tests/test_papers_ingest_api.py \
    tests/test_papers_view.py tests/test_papers_meta.py tests/test_papers_meta_api.py \
    tests/test_papers_meta_dualslot.py tests/test_taxonomy.py

# 前端纯契约（node）
node tests/paper_view.mjs && node tests/upload_pdf_intercept.mjs
```

- mutation 有牙（实测后已回退）：关掉导入接线 → `test_papers_meta_import.py` 8 例红；关掉手工字段保护 → 1 例红；删 view `notes` → 1 例红。
- 真实资料**只读**探针（脚本内联，未写用户库）：17 篇真实论文 → 标题 15/17、摘要 8/17、参考文献 17/17；`rlhf-helpful-harmless`、`deepseek-v2` 标题为空。
- live 浏览器验证（本地 uvicorn + 临时 store，非用户库）：导入合成 PDF 后库卡片显示 “A Study of Things”（非文件名）；`#paper/...` 阅读页有「重新提取元数据」按钮；点击（focus+Enter）触发 `POST /api/papers/{id}/metadata/extract` 200，状态显示“元数据已更新。”；参考文献区显示 `[1] Foo et al…` 与状态 `authors-unparsed`；无 console error。服务器已停止、临时目录已删。

## 未完成 / 限制（诚实标注）

1. **GROBID live 未验证**：环境无 GROBID 服务；仅离线 TEI fixture + 注入 transport。真实部署/资源成本未测。
2. **真实标题边界**：2/17 真实论文标题仍空、部分标题含作者/摘要残尾——属 issue 03 / Z2 的标题边界与印记识别领地，本任务未改 `structure.py`。
3. **未批量改用户库**：真实 17 篇仅只读探针；实际回填需用户另行授权。
4. **历史记录 title 不重写**：补提取后阅读页/库卡片显示 P2 标题，但 `record.json.title` 仍是原文件名（卡片经 `_paper_card_fields` 覆盖 headline）。若需写回记录标题，需新增 store 方法与迁移决策。
5. **前端 `click` 命令未触发**：AO `ao browser click e7` 未触发 handler，改用 `focus` + `press Enter` 成功；疑为 ref/命中问题，非页面缺陷（node 契约为准）。

## 主检出脏文件处置

主检出 `/Users/suyingke/Programs/OHO/graph2note` 有未提交改动（另一任务的 `graph2note/papers/view.py` 抽取 + `webapp.py` 改动等）。**本分支未使用、未复制该未提交 `papers/view.py`**：基线 f771b9d 的 `webapp._paper_view_payload` 为内联实现，本任务在其上做最小追加。已从主检出复制必要文档到本分支：`.scratch/paper-reading-reliability/{DIAGNOSIS.md,issues/02-metadata-import.md}`（当时均为 untracked，内容未改）；未复制 dispatcher 独占的 `BOARD.md`，也未在其上改动。未触碰其 `graph2note/papers/view.py`、`webstatic/workspace*`、`pyproject.toml` 等。

## 建议后续（suggested skills）

- **issue 03 / Z2 标题边界**：用 `diagnose` + 本 issue 的真实只读探针脚本校准 `_title_lines` 与印记抑制；真实样本见 `tests/fixtures/papers/real/`。
- **GROBID 试点**：部署验证时用 `diagnose`（外部服务超时/降级）+ 新增 live 标记测试，保持默认离线。
- **记录标题写回**：若维护者要“历史卡片彻底一致”，先裁决是否允许 `record.json.title` 迁移，再用本模块的 `preferred_document_title` 复用。
- **代码评审**：`code-review`（重点：P2 槽写入的幂等、失败隔离、view 契约加法）。
