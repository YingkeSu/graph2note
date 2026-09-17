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
- 真实资料**只读**探针（脚本内联，未写用户库）：17 篇真实论文 → 标题 15/17 非空且形状合理、**摘要 17/17**、参考文献 17/17；`rlhf-helpful-harmless`、`deepseek-v2` 标题诚实为空；`Transformer Circuits Thread AUTHORS` 类页眉仍可能被当标题（见残留）。
- **L2 口径更正**：上面的“15/17”是**非空计数，不等于正确**。正确性以真实 fixture 的显式 `gold`（人工核对标题/作者前缀/摘要开头）为准，由 `test_real_gold_title_authors_abstract` 断言；`gpt3-few-shot` / `gpt4-tech-report` 已纳入 `tests/fixtures/papers/real/`（来源 arXiv 2005.14165 / 2303.08774，sha256_16 = `97fd272f1fdfc186` / `c33a66dadca2388d`，与用户库 PDF 内容哈希一致）。
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

## Rework R1 — 独立审查整改（graph2note-136 裁决 CHANGES_REQUESTED）

审查报告：`graph2note-136/.scratch/reviews/prr-02-metadata.md`（复现快照 `/tmp/rwt-review-prr02`）。逐项回应：

- **B1（高，阻塞）真实 GPT-4/GPT-3 元数据** ✅
  - 根因：首页标题/作者/Abstract/引言常在同一段无空行；`_title_lines` 只找“带逗号的作者行”，找不到就把整段当标题；`_extract_abstract` 又因 `title_keys` 跳过被吞掉的 Abstract 标签。
  - 修复：`metadata._title_lines` 以**独立成行的 Abstract 标签**为硬边界 + 折行标题连接词判定；`_parse_authors` 逐行/逗号双形态；`_AFFIL_RE` 修正 `\b` 截断（University/Institute 等此前匹配不上）。
  - 证据：真实 GPT-4 → `GPT-4 Technical Report` / `["OpenAI"]` / 摘要 877 字符；GPT-3 → `Language Models are Few-Shot Learners` / 31 位作者 / 摘要 1778 字符。
- **B2（高，阻塞）错误标题写入 `record.title`** ✅
  - 新增 `metadata._title_is_plausible` 形状门禁（>300 字符 / >45 词 / 含 Abstract/Introduction / 多句 → 判为未提取），`parse_paper_meta` 记 `title-untrusted` 并置空；`preferred_document_title` 随之回落文件名。
  - 回归 `test_implausible_title_is_gated_and_falls_back_to_the_filename`；真实样本 `test_real_frozen_text_import_persists_and_views_gold` 断言 `record.title == gold title` 且 <120 字符。
- **B3（高，阻塞）人工清空被填回** ✅
  - `extract.merge_manual_meta` 改为“`source == manual` 即保留（含空值）”。回归 `test_manual_clear_is_preserved_by_reextract_and_restart`（幂等 + 重启 + view）。
- **M1（中）GROBID 可纠正低可信自动字段** ✅
  - `enhance.apply_meta_proposal(override_fields=…)`；`webapp._grobid_override_fields` 规则：非 `manual` 且 confidence ∈ {low, medium} 才可覆盖，证据标 `grobid:tei`。回归 `test_grobid_corrects_low_confidence_auto_value_but_never_manual` / `test_grobid_never_overrides_a_manual_field`。
- **L1（低）批量逐条状态** ✅
  - `POST /api/papers/extract-metadata` 对未知/非论文/失败分别返回 `unknown` / `not-paper` / `failed`，`total` = 请求条目数。回归 `test_batch_reports_unknown_and_not_paper_ids`。
- **L2（低）计数口径** ✅
  - 真实 fixture 增 `gold` 块 + `test_real_gold_title_authors_abstract`；本 handoff 与 issue 已改为“非空 ≠ 正确”，正确性以 gold 为准。新增 2 个真实 fixture（见上）。

### 证据与命令

```bash
# 定向
… -m pytest -p no:warnings tests/test_papers_meta_import.py tests/test_papers_meta_real.py \
    tests/test_papers_ingest_real.py tests/test_papers_meta.py
# 全量（离线，junit 计数）
… -m pytest -p no:warnings -q --junitxml=/tmp/prr02-fix/full.xml
# → 1431 passed / 0 failures / 0 errors / 0 skipped
```

真实库只读复测（未写入）：摘要 17/17（原 8/17）；标题 15/17 非空且形状合理，2 篇诚实为空。

### 残留（未转嫁、如实记录）

`Transformer Circuits Thread AUTHORS` 类**页眉**仍可能被当标题（形状合理但语义错误）；`doi` 仍可能回退到参考文献（`doi-from-references`）；`venue`/`keywords` 在 arXiv 样本上缺失（预期）。这些属 issue 03 / Z2 的首页印记与页眉抑制领地，本轮按约束未扩张到章节重排。

## Rework R2 — 独立复审第二轮的整改（R1 阻塞 + R2/R3）

审查报告：`graph2note-136/.scratch/reviews/prr-02-metadata-r2.md`（针对 `a2b2d16`/`a501497`）。

- **R1（高，阻塞）DOI 来源** ✅
  - `_extract_doi(front_text)`：只扫本论文首页元数据区域；参考/引用行跳过（`_CITATION_HINT_RE`），带标签的行还得像元数据（`_DOI_METADATA_MARKER_RE` 或该行基本只由 DOI/URL 构成），截断片段（后缀 <8 / 纯字母）拒绝；无证据 `meta.doi=""` + note `doi-not-found`。
  - 证据：GPT-4/scaling-laws 的 `meta.doi == ""`（原来分别是 `10.18653/v1/p19-1472` / `10.1145/3293883.3295710`）；真实库只读探针 DOI **0/17**；正例 `front_single_column` 仍为 `10.1109/tkde.2023.1234567`（high）。
- **R2（中）BERT 机构作者** ✅
  - `_parse_authors` 增加机构/组织裁剪（`_is_affiliation_like`/`_personal_name_tokens`，区分 `Google AI Language` 与 `the Ming Li Group`），并折叠 PDF 连字（`ﬁ`→`fi`）保住 `Zac Hatfield-Dodds`。`bert` 精确 4 人，gold 加 `author_count: 4`；真实库 2/17 无作者（deepseek-v3/r1）如实记录。
- **R3（低）Abstract 独立成段** ✅ 最小修复：`_abstract_block` 跨段收集正文（排除作者段落）。
- **year 同源检查**：真实 17 篇 year 均来自自身 arXiv/版权/页眉，无引用年份污染；未改逻辑。
- **保留**：B1–B3/M1/L1 回归未回退。

### R2 证据

```bash
… -m pytest -p no:warnings tests/test_papers_meta.py tests/test_papers_meta_import.py \
    tests/test_papers_meta_real.py tests/test_papers_ingest_real.py
# 全量：见下（本次交付运行 1439 passed / 0 failed / 0 skipped）
```

## Rework R3 — DOI 规范与来源归属分离（R4a/R4b）

审查报告：`graph2note-136/.scratch/reviews/prr-02-metadata-r3.md`（针对 `389b49e`/`b79d2fd`）。

- **R4a** ✅ 删除 `len(suffix)<8 or not any(digit)`：DOI 语法无最小长度/必须数字要求（ISO 26324 / DOI Handbook）。改为“语法（`_DOI_RE`）+ 来源归属（`_doi_line_is_metadata`）”分离；截断用折行上下文：仅当断在分隔符后、或下一行以 `. - _ /` 开头且拼接得到更长 DOI 时重建（保守，避免误并 `10.1000/182`+`2023`）。
  - 正例：DOI Handbook 示例 `10.1000/182`、`10.1000/186`；纯语法合成 `10.1000/xyz123`、`10.1234/abcdefgh`（注释标明未必注册）；跨行 `10.48550/arXiv.2405`+`.04434` → `10.48550/arxiv.2405.04434`。
- **R4b** ✅ 裸 DOI 仅在整行基本只含 DOI/URL 时接受；含散文的 `See 10.… for details.` 不接受；显式 `doi:` 需元数据标记或整行基本只含标签+DOI；参考条目 doi: 仍拒绝。
- **保留**：R1–R3/B1–B3/M1/L1 回归未变。真实库只读 DOI 0/17；front_single_column 正例仍接受。
- **矩阵**：短/纯字母/长/URL/doi:/本论文元数据/正文裸引用/参考文献/折行正负例，全部离线断言。

### R3 证据

```bash
… -m pytest -p no:warnings tests/test_papers_meta.py tests/test_papers_meta_import.py \
    tests/test_papers_meta_real.py tests/test_papers_ingest_real.py tests/test_papers_meta_dualslot.py
# 全量：1439 passed / 0 failed / 0 skipped
```
  - **规范来源核实**（2026-09-17，只读联网）：官方 doi.org“What is a DOI?”页面明确 DOI = prefix + suffix（斜杠分隔），并以其官方示例 `10.1000/182`（解析为 https://doi.org/10.1000/182）说明后缀可以很短；未发现“后缀最小长度/必须含数字”的规则，与 reviewer 引用的 ISO 26324 一致。`10.1000/xyz123`/`10.1234/abcdefgh` 仅作语法压测，未声称在线注册。
