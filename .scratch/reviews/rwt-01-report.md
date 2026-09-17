# 独立审查 — research-weekly-template issue 01「生成并阅读有证据的科研周报」

- **审查人**：AO worker `graph2note-138`（独立于被审 worker `graph2note-136`）
- **被审对象**：`/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-136`，分支 `dev/rwt-01-report`
- **初审提交**：`b27c4df` → CHANGES_REQUESTED（下面正文保留原判决）
- **复审提交（本裁决依据）**：**`83270eb`**（实现 `3e17c5b`，文档 `83270eb`；基线 `b27c4df`；工作树 clean）
- **handoff**：`.scratch/research-weekly-template/handoffs/01-research-report.md`
- **审查方式**：初审只读快照 `git archive b27c4df` → `/tmp/rwt01-snap`；复审只读快照 `git archive 83270eb` → `/tmp/rwt01b-snap`；复现脚本 `/tmp/rwt01b-review/{probe.py,probe2.py}`。**未修改被审分支、worktree、主检出或真实用户库。**
- **日期**：2026-09-17

## 复审 R1（SHA `83270eb`）：**APPROVE**

原报告 F1–F7 逐项关闭，复审在其独立快照上复跑并独立复现：

| # | 初审 | 复审结论 | 独立证据 |
|---|---|---|---|
| **F1** 高（阻塞）| CHANGES_REQUESTED | **关闭** | 改汇报人/日期后：`llm_calls=0`、`cached=True`、`rerendered=True`，返回 meta/markdown 内含新值且不含旧值；旧修订 `.md` 与 `.meta.json` 字节不变；新修订同指纹；重启后旧修订仍“张三”、新修订“李四”。 |
| **F2** 高 | CHANGES_REQUESTED | **关闭** | 启用专题 `process`（有正文无来源）与 `experiments`（正文+**非本材料**的外来来源）均不出现；`method`（正文+有效来源）出现。 |
| **F3** 中（PRD 偏离）| 需追认或改共享 store | **关闭（按协调决定）** | `POST/GET /api/digests` 统一边界：无 `template` → legacy（无 `report` 键）；`research_weekly` 走科研；同一张历史列表含两种模板；详情 legacy `{meta,markdown}`、research `{meta,markdown,sections}`；存储只有 `digests/`，未再建 `reports/`。 |
| **F4** 中 | CHANGES_REQUESTED | **关闭** | 顺序 `1、本周概览 → 2、本周进展 → 3、专题(存在的) → 4、问题与求助 → 附录：来源材料`；省略专题不留空号，附录不编号（API 与浏览器均核对）。 |
| **F5** 低 | 计数不一致 | **关闭** | 模型异常分支模块级返回 `llm_calls=1`；API 层为 502。 |
| **F6** 低 | range 旧标签 | **关闭** | 同日 `custom` vs `this_week`：`llm_calls=0`、`rerendered=True`、markdown 用新标签且不含旧标签、新修订同指纹。 |
| **F7** 提示 | 无可复跑命令 | **关闭** | `scripts/rw01_browser_evidence.sh` 实跑成功：临时 store + stub planner，浏览器文本复现 `1、本周概览 → 2、本周进展 → 3、过程记录 → 4、问题与求助 → 附录：来源材料`，无证据的「实验结果」不显示，meta 行 `汇报人：张三 · 日期：2026-09-13`，8823 无 console/网络错误。 |

### 复审复跑

```bash
# 只读快照
rm -rf /tmp/rwt01b-snap && mkdir -p /tmp/rwt01b-snap
 git -C /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-136 archive 83270eb | tar -x -C /tmp/rwt01b-snap
cd /tmp/rwt01b-snap && PYTHONPATH=/tmp/rwt01b-snap <venv>/python -m pytest -o addopts="" -p no:warnings -q \
  tests/test_research_report.py tests/test_report_view.py     # 28 passed
node tests/report_view_dom.mjs                                # all assertions passed
# legacy 不受影响
... -m pytest -o addopts="" -q tests/test_weekly_digest.py tests/test_digest_structure.py \
  tests/test_digest_budget.py tests/test_digest_view.py       # 99 passed
node tests/digest_view_dom.mjs                                # OK
# 全量（junit）
... -m pytest -o addopts="" -p no:warnings -q --junitxml=...  # 1396 passed / 0 failed / 0 skipped
# 浏览器证据
PORT=8823 PYTHON=<venv>/bin/python bash scripts/rw01_browser_evidence.sh   # 见上
```

### 兼容性观察（非阻塞，如实记录，未做迁移）

- **旧 dev `storage/reports/` 产物会被孤立**：b27c4df 开发版把科研报告写在 `storage/reports/`；统一到 `digests/` 后，这些文件仍在磁盘但不再被列表/详情读取（`GET /api/digests/<旧id>` → 404）。影响仅限未发布的开发版本地 store；按指示**未迁移**，需用户/维护者决定是否一次性搬迁。
- **`.report.json` 分节 sidecar 缺失/损坏有明确行为**：`load_section_bodies` 返回 `[]`，展示字段变化时不再重渲染而是回落到一次真实模型生成（1 次调用）并写新修订 —— 不会返回旧内容、不会崩溃；详情端点仍 200（用 meta 的 public sections + markdown）。代价是“缺失/损坏 sidecar + 纯展示变更”会多一次模型调用。
- **`resolve_range` 会重算 `label`**：API 无法注入任意 range 标签；F6 在 API 侧以同日不同 `kind`（custom/this_week）复现并通过。
- **旧 dashboard 可消费混合历史**：research meta 带 `digest_id` 与 `sections`（标题与 markdown `##` 标题一致），legacy `dashboard.js` 能列出/分段渲染；仅缺少模板徽章，属外观差异。

### 初审报告保留（历史记录）

以下为针对 `b27c4df` 的初审内容，保留以备追溯。

## 初审裁决（`b27c4df`）：**CHANGES_REQUESTED**

问题不在单测数量，而在两个用户可见的正确性缺陷 + 一个需明确裁决的 PRD 边界偏离。目标分支自测全绿（我复跑全量 **1393 passed**），但现有测试没有覆盖“改汇报信息后的返回内容”和“有正文但无证据的专题”，因此绿并不代表 AC 达成。

| # | 严重度 | 结论 |
|---|---|---|
| F1 | **高（阻塞）** | 改 `reporter` / `report_date` 后命中缓存，返回**旧**汇报人/日期内容与 meta，且不落新修订 |
| F2 | **高** | 已启用专题只要有正文就渲染；正文的 `source_document_ids` 为空（无证据）时仍生成“实验已完成/数值”等结论 |
| F3 | **中（PRD 偏离）** | 独立 `/api/reports*` + `storage/reports/` 未复用 PRD 明示的“现有周报创建/列表/详情边界”，形成平行存储 |
| F4 | **中（模板偏离）** | 章节顺序把「问题与求助」放在可选专题之前，且未实现 TEMPLATE 的连续编号 |
| F5 | 低 | 模型调用抛错时 `llm_calls` 报 0（实际已发起 1 次），与空回复分支报 1 不一致 |
| F6 | 低 | 指纹只用 from/to，忽略 range 的 `kind`/`label`：不同 kind 同日范围互相命中并返回旧 label |
| F7 | 提示 | 浏览器证据只有 `get text` 快照，无复跑命令；node DOM 契约通过 |

---

## 复现证据

### 环境
```bash
# 只读快照
rm -rf /tmp/rwt01-snap && mkdir -p /tmp/rwt01-snap
git -C /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-136 archive HEAD | tar -x -C /tmp/rwt01-snap
cd /tmp/rwt01-snap && PYTHONPATH=/tmp/rwt01-snap \
  /Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -c \
  "import graph2note.research_report as r; print(r.__file__)"   # → /tmp/rwt01-snap/...
```

### 基础复跑（确认自测结论，未发现单测造假）
```bash
cd /tmp/rwt01-snap && PYTHONPATH=/tmp/rwt01-snap ... -m pytest \
  -o addopts="" -p no:warnings -q tests/test_research_report.py tests/test_report_view.py
# 25 passed
cd /tmp/rwt01-snap && OPENCODE_API_KEY=dummy PYTHONPATH=/tmp/rwt01-snap ... \
  -m pytest -o addopts="" -p no:warnings -q          # 1393 passed in 154s（handoff 报 1391/1 skipped，环境差异，非缺陷）
cd /tmp/rwt01-snap && node tests/report_view_dom.mjs  # all assertions passed
```

### F1 复现（API 级，脚本 `/tmp/rwt01-review/repro_findings.py` Finding 1）
```text
planner calls: 1
r2.cached: True r2.meta.reporter: 张三 2026-09-13
r2.markdown contains 李四: False | contains 张三: True
r2.markdown contains 2026-09-14: False
```
- 请求 1：`POST /api/reports {range:custom, from:2026-09-01, to:2026-09-07, reporter:张三, report_date:2026-09-13}` → 200，模型 1 次。
- 请求 2：同范围但 `reporter:李四, report_date:2026-09-14` → 返回 200，`cached:true`、`llm_calls:0`，**meta.reporter 仍是“张三”、markdown 里仍是“张三/2026-09-13”**。前端 `report.js:748` 用 `result.report` + `result.markdown` 渲染，用户看到的是旧汇报人/旧日期。
- 根因：`graph2note/research_report.py:698-717` 命中缓存时**原样返回** `cached` meta + 落盘 markdown；`compute_report_fingerprint`（`research_report.py:237-285`）刻意不含 reporter/date；而 `save_report`（`research_report.py:572-620`）meta 里只存 `public_sections`（无 `markdown` 正文），因此**无法在零模型调用下按新汇报信息重排**。这不是“展示信息不进指纹”的自然结果，而是缺少“复用模型产物但用新汇报信息重渲染/新建修订”的落地。
- 与 issue 02 的 AC「修改生成相关输入使缓存正确失效，打开旧修订不再调用模型」方向一致，说明这个边界在 01 就必须做对，否则 02 会在错误基础上叠加修订。

### F2 复现（脚本 `/tmp/rwt01-review/repro_evidence.py`）
```text
sections: ['overview', 'progress', 'issues', 'experiments', 'appendix']
experiments section present: True | evidence ids: []
markdown contains invented conclusion: True   # “实验已完成，准确率 99%。”
```
- 模型对已启用的 `experiments` 返回正文但 `source_document_ids: []`（无证据），`build_report_sections`（`research_report.py:439-450`）只判 `body_text` 是否为空，非空即渲染并写入报告。
- PRD:50-52「事实来自材料或显式用户补充，未知结果不得补全」；TEMPLATE「缺证据不生成『完成实验』等结论」；issue AC1「无依据实验不出现」。现有测试 `test_build_sections_keeps_empty_issues_and_drops_evidence_free_module` 只覆盖“正文为空”的模块，没有覆盖“有正文但零证据”的情形。
- 建议：对可选专题（至少 `experiments`）做确定性门禁——`source_document_ids` 为空则不渲染该节，或显式标注「未标注证据」并默认不展示；同时保留“正文为空即省略”。

### F3 复现（结构性，无需脚本）
- 新增 `graph2note/research_report.py`（889 行）内含独立持久化：`reports_dir/_meta_path/_markdown_path`（`504-514`）、`list_reports`（`516`）、`load_report`（`536`）、`find_cached_report`（`552`）、`_new_report_id`（`562`）、`save_report`（`572`），与 `digest.py` 的 `digests_dir`（`1139`）、`list_digests`（`1155`）、`load_digest`（`1176`）、`find_cached`（`1281`）、`_new_digest_id`（`1327`）、`save_digest`（`1337`）成对重复。
- 新增 4 个端点 `/api/report-templates`、`POST/GET /api/reports`、`GET /api/reports/{id}`（`webapp.py:933-980`），而非扩展既有 `/api/digests` 创建/列表/详情（`webapp.py:893-931`）。
- 复现隔离性（脚本 Finding 7）：`digest.generate_digest` + `research_report.generate_report` 同库 → `digests/` 与 `reports/` 两个目录，两次模型调用，研究报不命中 digest 缓存。**隔离本身是好的**；争议在于是否应“扩展既有边界”。
- PRD 原文（`PRD.md:45-46`）：「扩展已有周报生成、持久化与阅读能力……Markdown/PDF 均消费同一快照，**避免平行存储各自漂移**」「**继续复用现有周报创建/列表/详情边界**，新增修订保存与导出能力」。

### F4 复现（脚本 Finding 5）
```text
render order: ['本周概览', '本周进展', '问题与求助', '过程记录', '附录：来源材料']
headings: ['## 本周概览', '## 本周进展', '## 问题与求助', '## 过程记录', '## 附录：来源材料']
TEMPLATE.md order expectation: 概览 -> 进展 -> 可选专题 -> 问题与求助 -> 附录
```
- TEMPLATE.md:11-24 明确「1、本周概览 → 2、本周进展 → 3、<可选专题> → 4、问题与求助（允许仅标题）→ 附录」并「编号随可选章节连续计算」。实现（`research_report.py:404-456` + `render_report_markdown:458`）固定 core 三节在前、专题在后，且无任何编号。

### F5 / F6 复现
```text
Finding 3: status: error | planner.calls: 1 | reported llm_calls: 0   # research_report.py:747-763
Finding 4: status: error | planner.calls: 1 | reported llm_calls: 1   # 空回复分支 :778
Finding 2: fingerprint(custom) == fingerprint(this_week) with same dates: True  # :255-256
```

---

## PRD 偏离判断（明确结论）

1. **F3 判定：偏离成立，需裁决（中）。**
   - 支持实现方：确实复用了 `digest` 的材料装配/预算/统计/分节解析/通道/session（handoff「复用而非重写」属实），旧四节路径零改动，隔离性经测试与本审查复现确认。
   - 不满足处：PRD 点名的是「创建/列表/详情**边界**」而非仅底层原语；`reports/` 与 `digests/`、`/api/reports*` 与 `/api/digests*` 构成两套并行历史。02 要在此之上做「修订 + 冲突检测」，两套修订史正是 PRD 警告的“平行存储各自漂移”。
   - 结论：**不是缺陷级 bug，但不能默认通过**。可选两条路：(a) 维护者显式追认该边界为正式契约（并记录 02–05 如何避免漂移）；(b) 在 02 开工前抽出共享 report store（路径/meta/list/load/find_cached/id 生成），两个模板共用端点边界。

2. **F4 判定：模板偏离成立（中）。** TEMPLATE.md 是 PRD 指定设计稿（「采用模板设计」），章节顺序与连续编号是设计的一部分，不是版式美化。要么改实现对齐，要么在 issue/handoff 记录明确的、经确认的偏离理由。

3. **reporter/date 不进指纹**：方向正确（纯展示变更不应触发模型费），但**单独成立不足以放行 F1**——不做零调用重渲染/新修订，用户体验就是“点了生成却得到旧报告”。

4. **未越界**：未提前实现 02–05（增量补充、批注、附录资产、PDF），除 01 必需的模板/章节整理外无越界重构。`digest.py`、`test_weekly_digest.py`、`test_digest_view.py`、`digest_view_dom.mjs` 零改动（已核 diff）。

---

## 逐条 AC 判定

| AC | 判定 | 依据 |
|---|---|---|
| AC1 科研版显示概览/进展/问题与求助；专题启闭排序；无依据实验不出现；空求助仅标题 | **未完全达成** | 章节渲染、启闭排序、空求助仅标题、空模块省略均已验证；但 **F2** 显示“有正文无证据”的实验节仍出现 |
| AC2 来源、统计、预算、模型失败可见；旧报告原样可读可导出 | 达成 | meta `documents/stats/budget/llm_mode`、UI 统计/预算/失败重试、死链灰显、legacy 模板委托 `/api/digests`；legacy 端点与文件均未变 |
| AC3 相同输入复用零调用；模板/模块变化不误用；空材料无调用 | 达成（含 F5 口径瑕疵） | `test_same_input_reuses_cache_with_zero_calls`、module/template 失效、legacy 指纹互斥、空材料零调用零落盘；我做 module 顺序变更 → 2 次调用复现成功。F5 仅 `llm_calls` 统计口径 |
| AC4 API 生成后重启读取 + 浏览器展示（离线 planner） | 达成 | `test_api_full_chain_generate_restart_read`、`test_report_view.py` + node DOM、handoff 证据文本（F7：仅快照，无复跑命令） |

## 值得肯定

- 模板身份/版本/提示版本独立，指纹覆盖 template/version/prompt/模块(含顺序)/材料内容哈希；未命中 digest 缓存（测试 + 我复现）。
- 空材料在装配后即返回，零模型调用、零落盘；模型失败不落盘、不崩溃。
- 旧四节路径与既有测试零改动；共享文件改动最小且是纯追加（`webapp.py` +54、`state.js` +1、`router.js` +1、`app.js` +1）。
- 持久化重启可读、损坏 meta 容错（`test_list_reports_ignores_corrupt_meta`）。
- handoff 主动披露了独立目录/端点决策与未做项，可追溯。

## 放行条件（建议）

1. **修 F1**：命中缓存且 `reporter`/`report_date`（或 range kind/label）与落盘 meta 不一致时，零模型调用地产出**正确**的返回内容与 meta——或将 `reporter/date` 纳入指纹并新建修订，或在 meta 中持久化分节正文并重渲染，或对 markdown 头部安全重写。必须新增“改汇报人后返回内容含新值且模型调用数不增”的回归测试。
2. **修 F2**：可选专题（至少 experiments）零证据不渲染/显式标注；新增“有正文但 `source_document_ids=[]` 的实验节不出现”的回归测试（mutation：去掉门禁应变红）。
3. **裁决 F3**：追认或改用共享 report store/端点边界，并把结论写回 PRD/BREAKDOWN 或 issue。
4. **处理 F4**：对齐 TEMPLATE 顺序与编号，或记录经确认的偏离。
5. 顺手修 F5（失败时 `llm_calls` 口径）与 F6（指纹纳入 kind/label）。

## 未做/限制

- 未做真实 macOS 应用、PDF、窄屏设备与逐像素视觉验收（属 03/05，issue 01 未要求）。
- 浏览器证据未独立复跑（需起本地服务 + 注入 planner）；我以 API 级 TestClient 复现 + node DOM 契约 + 审查方全量套件作为替代证据。
- `/tmp/rwt01-snap`（只读快照）与 `/tmp/rwt01-review/*.py`（复现脚本）保留供 dispatcher 复核；被审 worktree 未被触碰。
