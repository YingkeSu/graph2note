# P3 handoff — 论文阅读视图与库集成

Status: **ready-for-review（rework after reviewer-99 REJECT）**
Branch: `dev/P3-paper-view`（worktree `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-94`）
Base: merged `main` @ `aedf2de`（P1+P2+W1 已并入本分支）
Commits:
- `60dae9a` feat(papers): read-only `/api/papers` projection for the reading view
- `70f7d04` feat(papers): paper reading view (metadata, section nav, bibliography)
- `4f1a333` test(papers): offline backend + node contracts for the paper view
- `24c7ef2` docs(spw P3): handoff — paper reading view (ready-for-review)
- `413b631` Merge branch 'main' into dev/P3-paper-view（并入 P1/P2/W1）
- rework（本次）：`fix(papers): read the P3 view through the P1/P2 store seams…`

Issue: `.scratch/structure-paper-weekly/issues/P3-paper-reading-view.md`；契约：SPEC §2。
**未 push**；reviewer 负责合并后的真实数据集成验证。

## Rework — reviewer-99 两项阻塞缺陷

### 缺陷 A（已修）：P3 读不到 P1 真实章节
根因：P1 的持久化落点是 `documents/<id>/paper.json`（sections/fulltext/page_map），`record.json` 只落 `doc_kind` + `paper_sections` **计数**；P2 的 meta/references 落 `record.json` 的 `paper` 槽。旧 `_paper_blob` 只读 `record.json`，真实论文永远 `sections=[]`。
修复：`_paper_view_payload` 改走**公共 store 缝**——P1 的 `store.get_paper_payload(id)` 取 sections/fulltext/page_map，P2 的 `store.paper_payload(id)` 取 meta/references；不再解析任何原始 record 键（`_paper_blob`/`_paper_doc_kind` 已删除）。
附带修正：`PaperSection.page_start/page_end` 是 **0-based** PDF 页索引（`papers/model.py`），视图新增 `page_label`（经 `page_map` 转 1-based 显示），前端优先使用；`normalizeSection` 幂等（builder 二次归一化不再丢 `page_label`）。

### 缺陷 B（已修）：`GET /api/papers` 遮蔽 P1
P1 拥有 `GET /api/papers`（job 摘要**数组**）。旧的 P3 索引端点同路径且注册更早 → 遮蔽。已**删除** P3 索引端点与配套前端兜底（`applyPaperBadges`/`subscribeRender`/`ensurePaperIds` 一并移除）；库徽标改由 `library_cards.isPaperDoc` 直接读 `/api/documents` 摘要的 `doc_kind`（P1 已在 `_library_summary_fields` 暴露）。

### 新增回归/集成测试
- `test_view_reads_p1_sections_from_the_durable_paper_json`：用 P1 `save_paper_document` 真实写 `paper.json`，断言 record 只有计数、view 读回真实 sections（缺陷 A 哨兵）。
- `test_view_combines_p1_sections_with_p2_meta_and_references` / `..._record_slot` / durable reload：P1+P2 真实落点端到端。
- `test_p1_papers_endpoint_is_not_shadowed`：断言 `/api/papers` 仍是 list（缺陷 B 哨兵）。
- `test_documents_list_exposes_doc_kind_for_the_badge`：徽标数据源回归。

## 交付内容（对应验收项）

| 验收项 | 实现 | 证据 |
|---|---|---|
| 新视图经 router/index 注册；paper 从库列表/搜索进入论文视图；非 paper 路径不变 | `webstatic/js/views/paper.js` 经 `app.js` 导入并 `registerView("paper")`；同时复用注册 `#doc/<id>`（paper.js 在 document.js 之后导入）——库列表/统一搜索现有链接无需改动即可进论文视图；非 paper 直接 `renderDocumentRoute(route)`。`#paper/<id>` 是显式深链 | `tests/test_papers_view.py::test_paper_view_source_registers_both_routes_and_delegates_non_papers`；Playwright：`#doc/doc-ref-1`→work-zone、`#doc/paper-audit`→paper-zone |
| 章节导航树、点击定位、当前节高亮；无 sections 的 paper 回退现行视图 | `paper_view_core.sectionNavItems/buildSectionTree`；点击 `scrollIntoView` + 高亮；IntersectionObserver 维护 `aria-current`；`isPaperView()` 要求 paper 且有 sections，否则回落 document 视图 | `tests/paper_view.mjs` §1/§3；探针点击第 5 节→`.active=4` |
| 元数据卡片 + 参考文献列表按 SPEC §2；`resolved_document_id` 可跳转；缺字段不显示占位 | `paperMetaHtml`（空值整行省略）、`referenceListHtml`（仅 resolved 渲染 `#doc/<id>`） | `tests/paper_view.mjs` §4–§7；live：references=3、resolved=[doc-target,'',''] |
| 视觉/可达性基线：正文 ≥14px、辅助 ≥12px、对比度 ≥4.5:1、390px 无溢出、audit 3 宽度 0/0/0 | `style.css` 追加独立 P3 区块 | `test_paper_css_meets_the_reading_baseline`；`frontend_audit.mjs` 39 checks / 0 findings（含 `paper/paper-audit`、`doc/paper-audit` @1440/768/390），`/tmp/spw-p3-rework-audit-out/audit.json` |
| 只读消费、`/api/papers/*`；fixture 驱动、不依赖 P1/P2 | 端点只读；测试用 P1/P2 公共 API 真实落点驱动 | `tests/test_papers_view.py` 全离线 |
| 前端 node 契约 + 后端聚合端点测试离线；全量 pytest 绿 | `tests/paper_view.mjs` + `tests/test_papers_view.py` | 合并树全量 `pytest -p no:warnings` exit 0（**1202 collected / all passed**） |
| live 集成（reviewer 要求） | P1 真实导入→P2→P3 view | `/tmp/spw_p3_rework_live.py`（改自 reviewer 脚本）：**27/27 PASS**，12 个真实章节、页区间、meta/refs/resolved、P1 `/api/papers` 仍为 list |

## API 契约（P3 追加，只读；无新增 `GET /api/papers`）

```
GET /api/papers/{document_id}/view -> {
  "document_id", "doc_kind", "title",
  "meta": {title,authors[],year,venue,doi,abstract,keywords[],source},   # P2 paper_payload
  "sections": [{level,title,text,page_start,page_end,page_label}],       # P1 get_paper_payload
  "references": [{raw,title,authors[],year,doi,resolved_document_id}]    # P2 paper_payload
}   # 不存在 -> 404；非 paper -> doc_kind "" + 空数组
```

- `page_start`/`page_end` 保持 P1 原始 0-based；`page_label` 为 1-based 显示区间（`page_map` 映射）。
- 数据源：`store.get_paper_payload(id)`（P1）+ `store.paper_payload(id)`（P2）；畸形数据不抛异常，降级为空投影/空字段。

## 领地与共享文件

- 独占新文件：`webstatic/js/views/paper.js`、`webstatic/js/paper_view_core.js`、`tests/test_papers_view.py`、`tests/paper_view.mjs`。
- `webapp.py`：只在 `/api/documents/{id}` 之后**追加**独立 `/api/papers/*` 段（不在 `/api/papers` 裸路径注册 → 不遮蔽 P1）。
- `index.html`：`<main>` 内追加 `#paper-zone` 容器。`router.js`：追加 `#paper/<id>` 解析。
- `state.js`：追加 paper 元素与 ZONES 项。`ui.js`：`NAV_VIEW_ALIAS` 加 `paper:"library"`。`app.js`：追加 1 行导入。
- `library_cards.js`：追加 `isPaperDoc`/`paper` 字段/徽标（读 `/api/documents` 的 `doc_kind`）。
- `style.css`：仅末尾追加独立 P3 区块。`scripts/frontend_audit.mjs`：追加 `AUDIT_EXTRA_ROUTES`（默认不变）。`tests/taxonomy.py`：登记 `test_papers_view→webapp`。
- **未改** `store.py`/`ir.py`/`diagram*`/`digest.py`/`dashboard.js`/`upload.js`/`papers/*`；未触碰脏文件 `06-web-obsidian-vault-export.md`。

## 离线 / live 边界

- **已离线验证**：全量 pytest（1202）、node 契约、P1/P2 真实落点（paper.json + record slot）端到端、FileDocumentStore 重载、CSS 基线、`frontend_audit.mjs` 三宽度（0/0/0）。
- **已 live 验证（本地真实服务，非外部网络）**：合成 born-digital PDF → P1 导入（注入 router factory 一被构造即报错，证明零模型调用）→ P2 parse-metadata/references/resolve → P3 view，27/27 PASS。
- 环境无外部 API 依赖；本 issue 不触网。

## 风险与后续

1. **落点分叉（P2-R2 根因）**：P1 sections 在 `paper.json`、P2 slots 在 `record.json`。P3 现已通过公共 store 缝同时读取两者，对两种 store 都正确；是否把 P1/P2 落点收敛到单文件属 P1/P2 范畴，建议后续单独处理（本分支不动 store.py/papers/*）。
2. **`#doc` 路由覆盖**：paper.js 依赖「在 document.js 之后注册 `doc`」；后续新增模块若再注册 `doc` 需留意 `app.js` 导入顺序。
3. **DOI**：按「默认不访问外部服务」渲染为纯文本。
