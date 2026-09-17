# Handoff — 01 生成并阅读有证据的科研周报

Session: `graph2note-136` · Branch: `dev/rwt-01-report` · Base: `f771b9d` (local main)
Worktree: `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-136`
Issue: [issues/01-research-report.md](../issues/01-research-report.md) → `in-review`
Status: implementation + offline verification complete. **Not pushed, no PR, main untouched, BOARD untouched.**

## What was completed

科研周报全链路（周报模型 → 生成缓存 → 持久化 → 阅读 UI → 测试），并保留旧版四节小结兼容路径。

### Backend — new `graph2note/research_report.py`
- 模板注册表：`research_weekly` v1（本 issue）+ `weekly_summary`（旧 digest v2）。独立版本号
  `TEMPLATE_ID/TEMPLATE_VERSION/SCHEMA_VERSION/PROMPT_VERSION/GENERATOR_VERSION`；`templates_payload()`
  同时暴露两个模板与专题目录。
- 固定章节：`本周概览 / 本周进展 / 问题与求助`，其后接**已启用**的可选专题（按用户配置顺序），
  末尾确定性 `附录：来源材料`。
- 可选专题：catalog（实验结果/过程记录/方法备忘，**默认全部关闭**）+ 任意自定义标题专题；
  `normalize_modules()` 校验 key/title/enabled/顺序并拒绝与固定章节冲突的 key。
- 复用 `graph2note.digest`：材料装配/预算（`assemble_material`）、确定性统计、JSON 回复校验
  （`parse_section_reply`）、文本通道与 session（`digest_session`/`MAX_SUMMARY_TOKENS`）。
- 缓存指纹 = template id+version + schema/prompt version + 规范化专题配置(含顺序) + 材料指纹。
  reporter/report_date 属展示信息，**不进**指纹（改汇报人不触发模型调用）。
- 生成结果结构：`{status: ok|empty|error, generated, cached, llm_calls, sections, modules, report, markdown, message}`。
- 持久化 `storage/reports/<id>.md` + `<id>.meta.json`；`list_reports/load_report/find_cached_report` 重启可读。
- 模型失败 → `status=error` + message，不落盘；空材料 → `status=empty`，零调用、零落盘。

### Web API — `graph2note/webapp.py`（共享文件，最小接线）
新增 4 个端点：
- `GET /api/report-templates`
- `POST /api/reports`（body: range / modules / reporter / report_date / force；422 校验，502 模型失败）
- `GET /api/reports`
- `GET /api/reports/{id}`
旧 `/api/digests*` 未改动。

### Frontend
- 新视图 `graph2note/webstatic/js/views/report.js`（自注册 `#reports` 路由）：日期范围、汇报人/日期、
  模板选择、专题勾选 + ↑↓ 排序（localStorage 记忆）、历史、分节阅读（分节导航 / 来源跳转 / 死链灰显）、
  统计与材料预算条、生成方式徽章、缓存命中 / 空态 / 失败重试、前端 Blob 导出 Markdown。
  旧版模板选项委托 `/api/digests` 历史与生成（旧报告仍可读可导出）。
- `index.html`：侧栏 `#nav-reports` + 独立 `#report-zone`（`#digest-panel` 原样保留）。
- `style.css`：仅追加 `/* ============ RW01 ... */` 段。

### Tests（全部离线，无 live LLM）
- `tests/test_research_report.py`（20）：模板/专题规范化、prompt 规则、章节组装（空求助仅标题、
  无依据实验不出现）、缓存命中/模板版本失效/专题变更失效、legacy digest 不串缓存、空材料零调用、
  失败态、持久化+重启、API 全链、422/502、旧端点兼容。
- `tests/report_view_dom.mjs` + `tests/test_report_view.py`（5）：node DOM 契约（专题配置进 payload、
  分节渲染/来源/死链/统计预算/缓存/失败/legacy 委托/导出）+ 静态接线断言。
- `tests/taxonomy.py`：登记两个新测试文件（`notes` 模块；`test_research_report` 为 integration）。

## How to run the tests

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-136
OPENCODE_API_KEY=dummy uv run pytest tests/test_research_report.py tests/test_report_view.py -o addopts="" -q
node tests/report_view_dom.mjs
OPENCODE_API_KEY=dummy bash scripts/run_tests.sh notes webapp meta   # 405 passed
OPENCODE_API_KEY=dummy uv run pytest -o addopts="" -q -p no:randomly  # 全量：1391 passed, 1 skipped
```

## Acceptance criteria status

| AC | 状态 | 证据 |
|---|---|---|
| 科研版显示概览、进展、问题与求助；专题按配置启闭排序；无依据实验不出现，空求助仅标题 | ✅ | `test_build_sections_keeps_empty_issues_and_drops_evidence_free_module`、`test_prompt_asks_only_enabled_modules...`、`report_view_dom.mjs` 模块 enable/↑ 顺序 + 5 节渲染 |
| 来源、统计、预算和模型失败状态可见；旧报告原样可读可导出 | ✅ | meta `documents/sections/stats/budget`；`test_report_persists_meta_sections_sources_stats_budget`；UI 统计/预算/徽章/死链；`test_legacy_digest_endpoint_still_works_alongside_reports`、legacy 模板 DOM 断言 |
| 相同生成输入复用且零模型调用；模板/模块变化不误用旧结果；空材料无调用 | ✅ | `test_same_input_reuses_cache_with_zero_calls`、`test_reporter_and_date_changes_do_not_invalidate_cache`、`test_module_change_never_reuses_a_stale_result`、`test_template_version_change_never_reuses_a_stale_result`、`test_research_fingerprint_differs_from_legacy_digest_and_never_reuses_it`、`test_empty_material_calls_no_model_and_persists_nothing` |
| API 生成后重启读取及浏览器展示通过离线 planner 场景 | ✅ | `test_api_full_chain_generate_restart_read`（新 TestClient 重启读取）；真实浏览器：`graph2note.webapp:create_app` + 离线生成快照，`#reports` 渲染见 [`evidence/rw01-browser-report-text.txt`](evidence/rw01-browser-report-text.txt) |

已实现跨切 01 的模板/章节耦合整理，未新增纯重构票。未提前实现 02–05。

## Decisions & deviations

- **独立目录 `storage/reports/` + 独立 `/api/reports*`**：避免与 digest schema/缓存/端点互相污染；
  旧四节小结路径完全不动（AC2/AC3 的兼容与“不误用旧结果”由此保证）。
- **`reporter/report_date` 不进缓存指纹**：属展示信息，变更不应产生模型费用（PRD：纯布局/展示变更不调用）。
  若评审认为应进指纹，改动点集中在 `compute_report_fingerprint`。
- **可空章节策略**：core 三节始终渲染（问题与求助可为标题+空正文）；可选专题空正文即整节省略。
- **复用而非重写**：新材料预算/统计/通道/session/JSON 校验全部来自 `digest.py`，`research_report.py` 只新增
  模板身份、专题配置、research prompt/组装与 `reports/` 持久化。
- **未做的越界项（明确留给后续 issue）**：段落级增量补充/锁定/修订（02）、锚定批注双栏（03）、
  图文附录与可携带 Markdown（04）、PDF（05）。01 只做“整次生成 + 指纹缓存 + 阅读/导出”。
- **未做**：CLI 不支持科研周报（`digest` 子命令保持旧行为）；未做 PDF/打印；未做真实 macOS 应用视觉验收
  （issue 01 的 AC 未要求 PDF；浏览器面板已做一次真实渲染核对，截图服务当时不可用，故以页面文本为证）。
- `digest._meta_stats_view/_meta_budget_view/_normalize_reply` 为跨模块复用的私有函数；若后续要正式化，
  可在 digest 提升为公共 API（本 issue 未改 digest 以避免冲突）。

## Shared-file conflict points（给 dispatcher / 02–05 参考）

| 文件 | 改动 | 冲突风险 |
|---|---|---|
| `graph2note/webapp.py` | import + 4 个端点，插入在 `/api/digests/{id}` 之后 | 低；02/03 若扩展端点，注意 append 位置 |
| `graph2note/webstatic/index.html` | 侧栏 1 行 + `#report-zone`（`#digest-panel` 后、`#upload-zone` 前） | 中；03 锚定批注若改 dashboard/digest 区块，注意保持 `test_digest_view.py` 的 digest id 集合不变 |
| `graph2note/webstatic/js/router.js` | 1 行 route | 低 |
| `graph2note/webstatic/js/state.js` | `reportZone` ref + `ZONES` 1 项 | 低 |
| `graph2note/webstatic/app.js` | 1 行 import | 低（03 可能也加 import） |
| `graph2note/webstatic/style.css` | 末尾追加 RW01 段 | 低；追加式，勿插在 W2 段之前 |
| `tests/taxonomy.py` | 登记 2 个新测试文件 | 低；其他新测试文件同样在此登记 |

`dashboard.js`、`digest.py`、`test_digest_view.py`、`digest_view_dom.mjs` **未改动**。

## Docs provenance

Issue/PRD/TEMPLATE/REFERENCES/BREAKDOWN/issues/drafts 从主检出未提交目录
`/Users/suyingke/Programs/OHO/graph2note/.scratch/research-weekly-template/` 拷入本分支（内容一致，无改动）。
**未**拷入 `references/260907-latest.pdf` 与 `references/page-*.png`（约 2.7 MB 二进制，本 issue 实现不需要；
REFERENCES.md 中的绝对路径仍指向主检出）。若评审需要，可单独补拷。

## Open items / risks

- 浏览器面板截图当时返回 `SERVICE_UNAVAILABLE`，视觉证据为 `ao browser get text` 快照
  （见 evidence 文件）；如需逐像素截图，请在有截图能力时复跑一次。
- 真实 macOS 应用内阅读（US19/21）与 PDF 属 03/05，本 issue 未覆盖。
- iOS/窄屏仅做了 CSS 媒体查询（≤768 单栏），未做真实设备验收。

## Suggested skills

- `/code-review`（dispatcher 验收步骤 3）。
- `/impeccable`（若继续打磨 `#report-zone` 的视觉与信息层级；当前为功能级样式）。
- `/diagnose`（仅当后续出现缓存命中错误或指纹漂移类 bug）。

---

## Rework R1（2026-09-17）— 回应 reviewer `graph2note-138` 的 CHANGES_REQUESTED

审查报告：`/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138/.scratch/reviews/rwt-01-report.md`（e558de5）。
逐项回应与修复：

| # | 结论 | 修复与证据 |
|---|---|---|
| **F1** 高（阻塞）| 已修 | `research_report.generate_report` 命中指纹但 `_display_matches` 为假（汇报人/日期不同）时：从 `<id>.report.json` 结构化分节正文重渲染 markdown + 新 meta，`llm_calls=0`、`rerendered=True`，写入**新修订**，旧 `.md/.meta.json` 不改。回归：`test_reporter_and_date_change_rerenders_with_zero_calls`（断言 0 调用、新值、旧快照仍 张三、2 个修订、同指纹）。 |
| **F2** 高 | 已修 | `_numbered_entries` 对启用专题要求 `body 非空` **且** `_evidence_ids(body, allowed)` 非空（allowed=当前材料 document_ids）；有正文但空/失效/不属于当前输入的来源 → 整节省略。回归：`test_optional_module_with_body_but_no_evidence_is_not_rendered`、`test_optional_module_with_valid_evidence_is_rendered`。来源存在仅是必要条件，报告不声称已验证事实真实性；prompt 保留「已知/推论/猜想/待验证/计划」不确定性标注。 |
| **F3** 中（PRD 偏离）| 已按协调决定修 | 复用既有 `/api/digests` 创建/列表/详情边界：`POST /api/digests` 新增 `template`（默认 legacy `weekly_summary`，`research_weekly` 走科研生成）；列表/详情同一边界；科研报告写入共享 `digests/`（meta 含 `digest_id`+`template_id`），移除 `storage/reports/` 与 `/api/reports*` 平行端点/历史。旧四节 `.md/.meta.json` 不改写、不迁移、不删除；legacy 详情响应形状不变。回归：`test_legacy_digest_endpoint_still_works_alongside_reports`（两模板同列一张历史，legacy 无 `sections` 键）、`test_api_full_chain_generate_restart_read`。 |
| **F4** 中 | 已修 | 顺序改为 概览→进展→可选专题→问题与求助→附录；编号按实际章节连续（`1、`…），省略专题不留空号，附录不编号。回归：`test_build_sections_...` 与 node DOM 契约。 |
| **F5** 低 | 已修 | 模型异常分支 `llm_calls=1`（与空回复分支一致）。回归：`test_model_failure_is_a_status_and_persists_nothing`。 |
| **F6** 低 | 已修 | 指纹仍不含 kind/label（展示变化不触发模型）；`_display_matches` 比较 kind/from/to/label，不同则零调用重渲染新标签、写新修订。回归：`test_range_label_change_rerenders_with_the_new_label`。 |
| **F7** 提示 | 已补 | `scripts/rw01_browser_evidence.sh`：临时 store + 离线生成 + 注入 stub planner 起本地服务，打印 `ao browser open/get text/errors/screenshot` 命令；证据 `.scratch/research-weekly-template/handoffs/evidence/rw01-browser-report-text.txt`（实测 1、概览→2、进展→3、过程记录→4、问题与求助→附录，`实验结果` 无证据不显示，无 console error）。 |

### 影响面 / 冲突点更新

- `graph2note/research_report.py`：持久化改为共享 `digests/`（新增 `<id>.report.json` 分节正文 sidecar，与 legacy 的 `<id>.sections.json` 不冲突）；新增 `_display_matches`/`_sections_from_bodies`/`load_section_bodies`/`save_section_bodies`；`generate_report` 增加 `rerendered`。
- `graph2note/webapp.py`：`POST/GET /api/digests` 统一两模板（`template` 派发）；`GET /api/reports*` 已移除，保留只读 `GET /api/report-templates`。**02/03 若扩展周报，应在 `/api/digests` 边界内追加，不要再开平行存储。**
- `graph2note/webstatic/js/views/report.js`：全部改走 `/api/digests`；历史显示模板徽章。
- `scripts/rw01_browser_evidence.sh`（新）。
- `tests/test_research_report.py`（+5 回归相关）、`tests/test_report_view.py`、`tests/report_view_dom.mjs`、issue Comments。

### 证据

```bash
OPENCODE_API_KEY=dummy uv run pytest tests/test_research_report.py tests/test_report_view.py -o addopts="" -q  # 28 passed
node tests/report_view_dom.mjs                                     # all assertions passed
OPENCODE_API_KEY=dummy uv run pytest -o addopts="" -p no:randomly -q  # 1395 passed, 1 skipped
PORT=8823 PYTHON=python3 bash scripts/rw01_browser_evidence.sh     # then ao browser get text ...
```

未 push、未建 PR、未合并 main、未改 BOARD、未改他人分支或主检出。
