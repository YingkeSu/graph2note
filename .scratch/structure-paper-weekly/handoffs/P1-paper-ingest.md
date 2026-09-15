# P1 — 论文 PDF 导入管线（text-layer 直提 + 章节结构 + 扫描回退）handoff

Status: **ready-for-review**（离线全绿；live 未启用，见 §5）
分支：`dev/P1-paper-ingest`（基线 `main 3c64d60`，未 push）
日期：2026-09-15（worker dev-A / AO session graph2note-92）
领地：独占 `graph2note/papers/`（新建包）+ `tests/test_papers_ingest*.py` + `webstatic/js/views/upload.js`（追加式）；
只追加 `graph2note/webapp.py`（`/api/papers/*` 段）、`graph2note/store.py`（新方法 + 摘要追加一字段）；
另追加登记 `tests/taxonomy.py`（元测试强制要求，见 §2-3）、`pyproject.toml`（新包打包）。

**未碰**：`ir.py`、`diagram*`、`digest.py`、`dashboard.js`、`index.html`、`router.js`、`api.js`、`state.js`、`pdflib.py`（复用不复制，未改一行）、其他 issue 领地、脏文件 `.scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md`。未 push、未 `find /Users/suyingke`、未自审。

提交（3 个逻辑单元）：
- `bb464b9` feat(papers): deterministic text-layer paper ingest pipeline（papers/ 包 + store 追加 + pyproject）
- `6762e6d` feat(papers): append /api/papers/* import routes and PDF upload entry（webapp 追加段 + upload.js）
- `aefe9e8` test(papers): offline golden/fixture coverage for P1 ingest and API（51 个新用例 + taxonomy 登记）

---

## §0 总览（对任务书 AC 逐条）

| # | 验收项 | 结论 | 关键证据 |
|---|---|---|---|
| AC1 | 带文本层 fixture 走文本层直提、抽取文本与 fixture 一致、零 LLM | **达成** | §3-1：`read_text_layer` 页文本逐字符等于 fixture 插入文本；`process_paper` 在 router_factory=抛错桩下 done/text-layer；API 同口径 done |
| AC2 | 章节结构确定性切分（1/2/2.1/References → PaperSection 列表） | **达成** | §3-2：编号 + 规范名（Abstract/References/参考文献）+ 字号三类启发式；乱序输入可回放；每节 0-based page_start/page_end |
| AC3 | 无文本层自动判定 + 回退 VLM 逐页、provenance `source="vlm"`、判定离线确定性 | **达成** | §3-3：纯阈值判定（字符数/文本页占比，含 reason 与度量）；扫描 fixture 回退走注入 router_factory，页面文档 + 聚合论文文档 provenance.source=vlm |
| AC4 | 入库带 `doc_kind:"paper"` + 论文 provenance；store 只追加、既有调用不变 | **达成** | §2-2：`record.json` 带 `doc_kind`/`pdf_id`/`source_pdf`/`page_index`，payload 落 `paper.json`；`save_document` 未改（既有调用逐字段回归用例） |
| AC5 | `POST /api/papers/import` + 状态 + 结果；webapp 只追加；错误可操作；复用 pdflib 限制与 job 语义 | **达成** | §2-3、§3-4：webapp 纯插入（+163 行 0 删除）；415/400/413/422/404/409 全覆盖；`validate_pdf`/`PdfError`/原 PDF 路径/`render_pdf_page` 全部复用；job.json 持久化 + interrupted 归一 + retry 续跑 |
| AC6 | 页映射保留、原页查看沿用 `/source-page` | **达成** | §3-4：section 页区间（0-based）+ `page_map`（1-based）；`/api/documents/{id}/source-page` 与新增 `/api/papers/{id}/page/{n}` 均 200（测试断言） |
| AC7 | 全测试离线、新测试独立命名、全量 pytest 绿 | **达成** | §3-5：`pytest -p no:warnings` **1096 passed / 0 skipped**（基线 1048 + 新增 51 + taxonomy 若干；node 套件由 pytest 包装，含在内） |

---

## §1 实现（`graph2note/papers/`）

```
model.py      SPEC §2 契约：PaperSection / PaperMeta / PaperReference / PaperPage
              + PaperPayload(schema_version, source, sections, fulltext, page_map,
                meta, references, provenance)；extra="forbid"（无静默漂移）
textlayer.py  PyMuPDF 文本层直提（页→行：text/size/bold/全局阅读序 order）
              + decide_text_layer()：纯阈值判定（离线确定性、带 reason 与全部度量）
structure.py  纯函数切分：detect_headings()（编号 / 规范章节名 / 字号启发式）
              + split_sections()（前置内容保留、页区间、canonical 顺序）
pipeline.py   PaperJob（durable papers/<pdf_id>/job.json）
              + process_paper()：文本层直提（零 LLM）→ 无文本层回退 VLM
              + start_job()（后台 single-flight + watchdog）
              + result_payload()（只读结果形状）
```

### §1-1 数据流

1. 原 PDF 落 `pdflib` 既有位置 `<root>/pdfs/<pdf_id>/original.pdf`（`stable_pdf_id` 内容哈希，未复制实现）；
2. `read_text_layer()` → `decide_text_layer()`：
   - **text-layer**：`split_sections()` → `PaperPayload(source="text-layer")` → `store.save_paper_document()`；
   - **vlm**：`pdflib.process_pdf()`（未改一行：per-page attempts/timeout/幂等提交/拆分/去重全复用）
     产出 `{pdf_id}-pNNN` 页面文档 → 聚合为论文文档（每页一个 section、`provenance.page_document_ids`
     + `skipped_pages`）→ `PaperPayload(source="vlm")` → 同一 store 提交路径。
3. 论文文档 id 确定性：`paper_document_id(pdf_id) = "<pdf_id>-paper"`（与页文档 `-pNNN` 不冲突），
   record 带 `pdf_id`/`source_pdf`/`page_index=0`/`page_number=1` → 直接接入 `/source-page`。

### §1-2 判定规则（离线确定性，AC3）

每页非空白字符数 ≥ `MIN_PAGE_CHARS=60` 记为「有文本页」；文档走文本层当且仅当
`总字符数 ≥ MIN_TOTAL_CHARS=200` 且 `有文本页数 ≥ 1` 且 `有文本页占比 ≥ MIN_TEXT_PAGE_RATIO=0.30`。
阈值全是模块常量 + `decide_text_layer(..., min_*=...)` 可注入；判定结果（source/reason/度量/阈值）
写入 provenance 与 job，供 UI 解释与复现。扫描版常见的印章/页眉（几十字符）不会误判为 born-digital。

### §1-3 切分规则（AC2）

- **编号**：`1` / `2.1` / `2.1.3`（前缀 ≤8 字符、层级 ≤4）；拒绝小写开头/jest 句尾/句子式行，
  避免把「1 the results are better …」当标题；
- **规范名**：Abstract/Introduction/References/Bibliography/Conclusion/Appendix/摘要/引言/参考文献/
  结论/致谢/附录/目录（大小写、空白、标点折叠后匹配），level=1；
- **字号**：正文大小为「按字符数加权的字号众数」，≥ 正文 + `HEADING_SIZE_DELTA=1.0pt` 且非句子式
  的行成为标题，字号越大层级越高（最大 → level 1）。

切分输入是 `TextLine` 纯数据，所有 tie-break 是全序的（字符权重 → 字号 → 源顺序），
因此同一输入无论列表顺序都产生逐字段相同的 sections（有专门回放用例）。

---

## §2 共享文件只追加证据

### §2-1 `webapp.py`（+163 / −0）

- 第 74 行插入一行 `from . import papers`（既有导入行未改）；
- `create_app()` 末尾、`# ---- static frontend ----` 之前**纯插入**一个
  `# ---- paper PDF import (SPW I-track / P1; appended /api/papers/* only) ----` 段：
  `app.state.paper_jobs(_lock)` + 4 个本地 helper + 7 条路由，全部前缀 `/api/papers/*`：
  - `POST /api/papers/import`（multipart，同步校验后异步跑）
  - `GET /api/papers`（列表）、`GET /api/papers/{id}`（状态）
  - `GET /api/papers/{id}/result`（结果；未完成 → 409）
  - `GET /api/papers/{id}/original`、`GET /api/papers/{id}/page/{n}`
  - `POST /api/papers/{id}/retry`
- 既有 `/api/pdf/*`、`/api/documents/*` 等一行未改（回归：`tests/test_webapp.py`、`test_pdf_upload.py`、
  `test_pdf_job_recovery.py` 全绿；另有专门用例断言其他路由仍 200）。

### §2-2 `store.py`（+143 / −0）

- `DocumentStore`(ABC) 末尾追加 4 个**非 abstract** 方法：`save_paper_document`（委托既有
  `save_document` 后写 `doc_kind`+payload）、`set_paper_payload`、`get_paper_payload`、
  `update_paper_payload`（P2 填 meta/references 的接缝）；
- `FileDocumentStore` 末尾覆写 `set_paper_payload`/`get_paper_payload`：payload → `<doc>/paper.json`，
  `record.json` 只加 `doc_kind`/`paper_source`/`paper_sections`（列表页不读大文件）；
- `_library_summary_fields` 追加一个键 `doc_kind`（供 P3 库列表识别论文，additive，不移除任何键）；
- **既有 `save_document` 未改一行**；有专门用例断言普通提交 `doc_kind` 不存在、version 语义不变。

### §2-3 越界说明（诚实标注）

- `tests/taxonomy.py`：仓库元测试 `tests/test_taxonomy.py` 强制每个 `tests/test_*.py` 必须登记模块归属，
  否则全量测试红。因此**追加**了 2 行 FILE_TO_MODULE + 1 行 INTEGRATION_FILES + 1 行 SLOW_FILES；
  未改任何既有行。
- `pyproject.toml`：`packages` 列表**追加** `"graph2note.papers"`（否则打包遗漏新包）。
- 测试文件命名为 `tests/test_papers_ingest.py` / `tests/test_papers_ingest_api.py`，均落在任务书
  `tests/test_papers_ingest*.py` 领地通配内。

---

## §3 验收（全部本轮自跑，离线）

### §3-1 AC1 文本层直提 + 零 LLM

`tests/test_papers_ingest.py::test_text_layer_extraction_matches_fixture_text`：
合成 PDF（`page.insert_text`，字号 10/12/13/15/18）→ `read_text_layer` 页文本与 fixture 插入文本
**逐字符相等**；`fulltext` 逐行相等。

`::test_process_paper_text_layer_zero_llm`：注入 `router_factory` 为「一被调用即抛错」的桩，
`process_paper` 仍 done / `source="text-layer"` / `calls == []`；`tests/test_papers_ingest_api.py::
test_paper_import_text_layer_chain` 同口径走 TestClient（`_boom_factory`）done。

### §3-2 AC2 章节切分

`::test_split_sections_from_text_lines_numbered_and_named` 断言
`[(level,title)] == [(1,"A Study of Things"),(1,"Abstract"),(1,"Introduction"),(1,"Method"),
(2,"Overview"),(1,"References")]` 且 Method（page 1）与 Introduction（page 0）页区间正确、
空正文节保持为空；`::test_split_sections_page_range_spans_pages` 覆盖跨页节（0→1）；
`::test_font_size_heading_detected_without_numbering` 覆盖纯字号启发式；
`::test_body_size_sentence_is_not_a_heading` / `::test_canonical_chinese_headings_detected` 覆盖反例与中文；
`::test_split_sections_is_replayable_for_any_input_order` 用**逆序**输入断言输出逐字段相同。

### §3-3 AC3 扫描回退

`::test_decide_text_layer_falls_back_for_scan`：纯图像 PDF → `source="vlm"`、0 文本页；
`::test_decide_text_layer_boundaries_are_explicit_and_offline` 用 3 组阈值证明判定完全由显式阈值驱动；
`::test_scan_pdf_has_no_text_layer` 断言 `char_count == 0`。
`::test_process_paper_vlm_fallback_uses_router_factory`：注入 `RouteARouter`+golden IR →
done/`source="vlm"`、router 被调用、`provenance.page_document_ids == result.page_documents`、
每页文档保留 `pdf_id`/`page_index`（issue 08/09 映射）；API 侧
`test_paper_import_falls_back_to_vlm_for_scan` 同口径（扫描 fixture + 注入 router，CI 不触网）。

### §3-4 AC4/AC5/AC6

- `test_process_paper_commits_paper_document_with_provenance`：`doc_kind=="paper"`、`pdf_id`、
  `source_pdf`、`page_index/page_number`、`versions[0].provenance=="paper-text-layer"`、库列表带 `doc_kind`。
- `test_save_paper_document_is_durable_across_store_instances`：重开 `FileDocumentStore` 后 `paper.json` 仍可读。
- `test_update_paper_payload_merges_p2_slots`：P2 槽位可合并（无新版本）。
- `test_save_document_behaviour_is_unchanged`：Session/File 两 store 的既有提交路径零变化。
- API：`test_paper_import_text_layer_chain`（import/status/result/list/original/page/source-page/library 全链）、
  `test_paper_import_is_idempotent_for_same_bytes`（同字节重传不新增 version）、
  错误 `415/400/422/413/422`、`test_paper_status_and_result_unknown_ids`（404×4）、
  `test_paper_result_before_completion_is_actionable`（409 + 可操作文案）、
  `test_paper_retry_resumes_a_failed_job`（失败 → 翻桩 → retry → done，已完成 no-op）、
  `test_paper_job_interrupted_is_reconciled_on_reload`（durable job 归一 interrupted 并落盘）。

### §3-5 全量测试

```
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-92
/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest -p no:warnings
1096 passed in 134.51s        # 0 failed / 0 skipped；含全部 node 套件（pytest 包装调用 node）
```

新增用例 51（`test_papers_ingest.py` 34 + `test_papers_ingest_api.py` 17），基线 1048 + 51 ≈ 1096（含 taxonomy 元测试计数差异）。

前端：`upload.js` 逻辑追加（capture 阶段仅对 PDF 拦截），新增用例含 ES module 语法检查
（`node --check`）与「未触碰 router.js/api.js/state.js」纪律断言；仓库既有 node 契约套件全绿。

### §3-6 live 边界

本轮**未发起任何 live LLM 调用**：AC1–AC7 全部由离线 fixture/注入桩覆盖。
主仓 `.env` 含 KIMI/DEEPSEEK 通道 key（存在但**未读取值、未打印、未写产物**）；
若 reviewer 需要 live 复验，通道名分别为 `kimi`（`GRAPH2NOTE_GATEWAY=kimi`）与 `deepseek`（备援），
可对扫描版样本真实走一遍 VLM 逐页回退（本分支不改 pdflib，风险面在既有 08/09 路径）。
无 key 环境下全链路可用：文本层路径根本不构造 router。

---

## §4 复现命令

```bash
W=/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-92
PY=/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python
cd $W
$PY -m pytest -p no:warnings tests/test_papers_ingest.py tests/test_papers_ingest_api.py   # 51 passed
$PY -m pytest -p no:warnings                                                               # 1096 passed
node --check <(cat graph2note/webstatic/js/views/upload.js)  # 语法（或 pytest 内的等价用例）
```

手工链路（离线）：构造带文本层 PDF → `POST /api/papers/import` → `GET /api/papers/{id}`（done,
source=text-layer）→ `GET /api/papers/{id}/result`（sections/pages/fulltext）→
`GET /api/documents/{document_id}/source-page`（原页 PNG）。

---

## §5 诚实边界与已知取舍

- **无真实论文样本**：fixture 全部为合成 PDF（真文本层 / 纯图像两种），未用真实论文 PDF 验证排版多样性；
  切分启发式（字号众数、编号正则）对复杂双栏排版（栏内文本流、跨栏标题、行内公式）未做专项评估。
- **VLM 回退产出聚合论文文档**：扫描版论文除页面文档外，额外聚合成一个 `doc_kind="paper"` 文档
  （每页一个 section、markdown 由页面文档拼接、页区间单页）。这是为让 AC4「入库带 doc_kind」在回退路径
  也成立所做的取舍；若 P2/P3 认为重复（页面文档已足够），可只保留页面文档——契约可回归。
- **文本层路径的 `ir_json` 是空 `DocumentIR`**：论文文本层无 diagram/VLM blocks；正文以确定性 Markdown
  （`#` 标题层级 = section level+1）落 `markdown.md`。若 P3 需要块级 IR 渲染章节，需要另行扩展（P1 未做）。
- **页号口径**：`PaperSection.page_start/page_end` 与 `page_index` 一致是 **0-based**（SPEC 未规定），
  `page_map` 同时给 1-based `page_number`；P3 展示时需 +1（已在 `model.py` docstring 与 result 的
  `pages` 数组标注）。
- **`paper.json` 与 `record.json` 分离**：全文/章节放 `paper.json`，`record.json` 只留 `doc_kind` 摘要。
  `get_document()` 不自动合并 payload（未改既有方法）；需要 payload 的调用方用
  `store.get_paper_payload(doc_id)`（P1 的 `/result` 端点即此路径）。P3 若直接读 `/api/documents/{id}`
  将看不到 sections——这是有意的接缝，P3 用 `/api/papers/*` 只读端点（任务书 P3 AC5 亦如此约定）。
- **job 级 watchdog 不取消已提交线程**：`start_job` 超时只把 job 标 failed（与既有 PDF JobRunner 同语义），
  worker 线程可能继续跑完（其提交是幂等的）；未做真正的中断取消。
- **前端未做 Playwright 几何巡检**：upload.js 只加逻辑分支（无布局/样式改动），本轮以语法检查 + 源码契约
  断言 + 既有 node 套件覆盖；论文阅读视图的视觉验收属 P3。
- **`/api/papers/{paper_id}` 的路径参数未加白名单校验**（与既有 `/api/pdf/{pdf_id}` 同口径，
  本地单用户应用）；如需加固，建议对 08/09 与 P1 统一处理。
- 未合并、未自审、未 push；`main` 与 origin 均未改动。
