# 独立审查 — paper-reading-reliability issue 02「接通论文导入的元数据与参考文献提取」

- **审查人**：AO worker `graph2note-136`（独立于被审 worker `graph2note-138`；同时被 138 审自己的周报，未自审）
- **被审对象**：`/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138`，分支 `dev/prr-02-metadata`
- **核实提交**：HEAD `e558de5`；其中元数据实现提交为 `368e3c4`（`e558de5` 只新增本目录之外的 review 文档，未改 `graph2note/` 或 `tests/`，已用 `git diff --stat 368e3c4..HEAD -- graph2note tests` 核实为空）
- **审查方式**：只读快照 `git archive HEAD → /tmp/rwt-review-prr02`；复现测试放在快照 `tests/`，**未修改被审分支、他人 worktree、主检出或真实用户库**
- **日期**：2026-09-17

## 裁决：**CHANGES_REQUESTED**

现有 18 例离线测试全绿，失败隔离/幂等/批量/GROBID seam 实现质量良好；但 **AC1 在真实 GPT-4/GPT-3 上不成立**，且 **人工清空字段会被重新提取覆盖**，二者均为用户可见的阻塞缺陷，不能转交 issue 03 了事。

| # | 严重度 | 结论 |
|---|---|---|
| B1 | **高（阻塞）** | AC1 未达成：真实 GPT-4 / GPT-3 的标题被解析成 2.1–2.3 KB 首页大段文本，作者为正文碎片，摘要为空 |
| B2 | **高（阻塞，本分支引入的回归）** | 导入把上述错误标题直接写进 `record.title`（`pipeline.py:428/450`、`558/589`），库卡片/markdown 会显示整段首页，比原文件名更不可用 |
| B3 | **高（阻塞）** | 人工清空的字段在重新提取时被填回（`extract.py:121`），违背 AC2「保留手工字段」与 Y1「PATCH 清字段」语义 |
| M1 | 中 | GROBID「只填空字段」策略使其无法纠正错误但非空的确定性标题，无法承担 issue 要求的标题候选解析器角色 |
| L1 | 低 | 批量端点对未知/非论文 `document_ids` 静默跳过，`total=0` 无逐条状态 |
| L2 | 低 | handoff 的「标题 15/17」是非空计数，不等于正确；其中多数为标题+作者/摘要残尾 |

---

## 复现证据

### 环境（只读快照）
```bash
rm -rf /tmp/rwt-review-prr02 && mkdir -p /tmp/rwt-review-prr02
git -C /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138 archive HEAD \
  | tar -x -C /tmp/rwt-review-prr02
cd /tmp/rwt-review-prr02 && PYTHONPATH=/tmp/rwt-review-prr02 \
  /Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -c \
  "import graph2note; print(graph2note.__file__)"   # → /tmp/rwt-review-prr02/...
```

### 基础复跑（确认自测为真，无造假）
```bash
cd /tmp/rwt-review-prr02 && PYTHONPATH=/tmp/rwt-review-prr02 \
  .venv/python -m pytest -p no:warnings -o addopts="" -q tests/test_papers_meta_import.py
# 18 passed
# 全量（排除审查者新增文件）：1385 passed + 1 failed（taxonomy 元测试仅因审查者新文件未登记，非分支缺陷）
```

### B1 — AC1 在真实 GPT-4/GPT-3 上失败（决定性）
只读真实库 `/Users/suyingke/Library/Application Support/Graph2Note/storage`（P1 `paper.json.fulltext`，17 篇论文），直接跑 `extract.run_extraction`：

```text
papers=17  title_nonempty=15 title_empty=2 abstract_nonempty=8 authors_nonempty=17

id: pdf-97fd272f1fdfc186-paper   (gpt3-few-shot)
parsed title (len 2305): 'Language Models are Few-Shot Learners Tom B. Brown∗ Benjamin Mann∗
  Nick Ryder∗ Melanie Subbiah∗ Jared Kaplan† ... OpenAI Abstract Recent work has demonstrated ...'
parsed authors: ['Johns Hopkins University', 'OpenAI Author contributions listed at end of paper. arXiv:.v [cs.CL] Jul']
abstract empty: True

id: pdf-c33a66dadca2388d-paper   (gpt4-tech-report)
parsed title (len 2110): 'GPT-4 Technical Report OpenAI∗ Abstract We report the development of GPT-4,
  a large-scale, multimodal model which can accept image and text inputs ...'
parsed authors: ['On the MMLU benchmark [', ']', 'an English-language suite of multiple-choice questions ...', ...]
abstract empty: True
```

- 真实标题应为 `GPT-4 Technical Report` / `Language Models are Few-Shot Learners`；解析结果把**标题+作者+摘要+引言**整段当成 title（分别是 2110 / 2305 字符）。
- GPT-4 与 GPT-3 的 abstract 均为空、authors 均为正文碎片。**这三项恰好是 AC1 明确点名的 GPT-4/GPT-3 样本**，因此 AC1 不成立。
- 该行为由既有 P2 `parse_paper_text` 决定，但 issue 02 的 AC 要求的是“导入后正确显示”，且 orchestrator 明确要求不得把真实标题问题直接推给 03。当前实现既未设标题形状门禁，也未以 GROBID 兜底（见 M1）。

### B2 — 错误标题被持久化为 `record.title`（本分支新增行为）
`pipeline.py:428-430`（VLM 路径 `558-560`）：
```python
display_title = extract.preferred_document_title(
    title, fulltext=layer.fulltext, front_text=front_text, source="text-layer")
...
store.save_paper_document(document_id=document_id, title=display_title, ...)   # :450
```
`preferred_document_title`（`extract.py:159-176`）在解析出非空 title 时无条件返回它。对上述真实论文，新导入会把 2 KB 首页文本写入 `record.title`，并作为 `render_paper_markdown` 的一级标题、库卡片 `headline`。这相对基线（文件名）是**新增的回归**：文件名虽不理想但可用，2 KB 正文块不可用。合成干净样本的测试（`test_library_card_reads_the_same_title_as_the_reading_view`）无法暴露此问题。

### B3 — 人工清空字段被重新填回
快照内新增 `tests/test_review_manual_clear.py`（2 例）：
```text
test_manually_cleared_title_is_not_refilled_by_reextract  FAILED
  AssertionError: manual clear was overwritten: title='A Study of Things',
  provenance={'source': 'text-layer', 'confidence': 'high', 'evidence': 'A Study of Things'}

test_manually_cleared_authors_are_not_refilled_by_reextract  FAILED
  AssertionError: manual clear was overwritten: authors=['Alice', 'Bob']
```
复现步骤（与测试一致）：
1. 导入论文 → title=`A Study of Things`（provenance `text-layer`）。
2. `PATCH /api/papers/{id}/metadata {"meta":{"title":""}}` → 200，title 空，provenance `manual`（Y1 语义，`webapp.py:2613-2650`）。
3. `POST /api/papers/{id}/metadata/extract` → title 被重新填回 `A Study of Things`，provenance 退回 `text-layer`。

根因在 `graph2note/papers/extract.py:121`：
```python
if prov.get("source") != MANUAL_SOURCE or _is_empty(value):
    continue          # ← 值为空 ⇒ 不视为手工字段 ⇒ 被新鲜解析覆盖
```
`merge_manual_meta` 只在“manual 且值非空”时保留，因此**用户显式清空**的字段无法被保护。应改为：`source == "manual"` 即保留存储值（含空值），或记录显式 `cleared` 状态；需补“清空后重提取仍为空”的回归用例。

### M1 — GROBID 无法纠正错误标题
`_re_extract_paper`（`webapp.py:2540-2570`）把 GROBID 结果作为 `proposal`，经 `enhance.apply_meta_proposal`（`enhance.py:168-210`）**只填空字段**。当确定性标题错误但非空（B1 情形）时，GROBID 的正确标题不会写入。issue 02 要求“用 GROBID 作为学术标题/作者/参考文献候选解析器”，当前接线下它对最关键的错误标题无能为力；需给出方向（如标题形状不可信时视为空、或允许证据充分的候选覆盖），否则该 seam 的实用价值有限。

### L1 / L2
- `webapp.py:2580-2600` 批量端点：`document_ids` 中的未知 id（或非论文 id）不会出现在 `results`，`total` 只统计命中的论文，调用方无法区分“不存在/非论文/失败”。
- handoff「真实资料只读验证：标题 15/17」为非空计数；本次复跑同口径为 15/17 非空，但其中 GPT-4/GPT-3 等为整段首页，属“非空但错误”。报告与 AC 应以“正确”而非“非空”为准。

---

## 已通过验证（正向结论）

- **失败隔离**：`extract_and_persist` 捕获解析异常返回 `failed` 且不动旧槽（`extract.py:212-260`）；`run_metadata_extraction`（`pipeline.py:383-410`）与 `_re_extract_paper` 双层兜底；`test_import_survives_a_failing_metadata_pass`、`test_batch_isolates_a_failing_item` 绿。
- **幂等**：notes 有序去重，重复提取 meta/provenance/references 字节一致；`test_reextract_is_idempotent_and_preserves_manual_fields` 绿（但其手工字段为非空场景，未覆盖清空）。
- **批量部分失败**：逐项隔离并计数 `ok/empty/failed`；单论文过滤可用。
- **import→persist→view 一致**：`result_payload` 先读 P2（`pipeline.py:326-365`），`_paper_view_payload` 合并 P1/P2（`webapp.py:1150-1170`），`/api/documents` 卡片经 `_paper_card_fields` 读同一 P2 标题（`webapp.py:212-231`）；重开 store 后仍一致（测试绿）。
- **不伪造 DOI/库内链接**：参考文献 `raw` 保留，`notes` 暴露 `authors-unparsed`，`doi`/`resolved_document_id` 无证据为空；`test_reference_status_keeps_raw_text_and_never_fabricates_a_link` 绿。
- **GROBID seam**：可选、可注入、缺配置/不可达降级并记 `grobid-unavailable:*`；TEI→字段为纯函数；离线 fixture 测试绿。live 未验证（环境无服务）已在 handoff 诚实标注。

## AC 逐条

| AC | 结论 | 说明 |
|---|---|---|
| AC1 新导入 GPT-4/GPT-3 正确显示标题/作者/摘要 | **未达成** | B1/B2：真实两篇标题为 2 KB 首页块、作者碎片、摘要空 |
| AC2 历史补提取、幂等、可重试、保留手工字段 | **部分未达成** | B3：人工清空被填回；非空手工字段与幂等通过 |
| AC3 References 区解析并显示状态、不伪造 | 达成 | 见正向结论 |
| AC4 导入/metadata/view 一致、重启一致 | 达成 | 见正向结论 |
| AC5 衔接 Y1 清字段与 Y5 作者摘要 | **未达成** | B3 未覆盖 Y1 清字段；Y5 回流用例通过 |

## 建议（按优先级）

1. **B3**（最小改动）：`merge_manual_meta` 对 `source == manual` 无条件保留存储值（含空），或在 provenance 增记 `cleared` 并纳入保留；补“清空后重提取仍空”回归。
2. **B1/B2**：给 `preferred_document_title` / 导入标题加**形状门禁**（如超长、含 `Abstract`/`Introduction`/作者串、跨页）→ 视为未提取，回落文件名/留空；必要时结合 GROBID；补真实 GPT-4/GPT-3 风格的回归 fixture（可用 `tests/fixtures/papers/real/` 增样）。
3. **M1**：明确 GROBID 在“标题疑似错误”时的可覆盖策略与证据标注。
4. L1：批量对未命中 id 返回 `unknown`/`skipped` 条目。
5. 报告口径：把“非空标题数”改为“正确标题数”，避免 AC1 被非空计数掩盖。
