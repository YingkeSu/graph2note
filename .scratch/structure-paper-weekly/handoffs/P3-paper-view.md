# P3 handoff — 论文阅读视图与库集成

Status: **ready-for-review**
Branch: `dev/P3-paper-view`（worktree `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-94`）
Base: `main` @ `3c64d60`
Commits:
- `60dae9a` feat(papers): read-only `/api/papers` projection for the reading view
- `70f7d04` feat(papers): paper reading view (metadata, section nav, bibliography)
- `4f1a333` test(papers): offline backend + node contracts for the paper view

Issue: `.scratch/structure-paper-weekly/issues/P3-paper-reading-view.md`；契约：SPEC §2。
**未 push**；reviewer 负责 P1→P2→P3 合并后的真实数据集成验证。

## 交付内容（对应验收项）

| 验收项 | 实现 | 证据 |
|---|---|---|
| 新视图经 router/index 注册；paper 从库列表/搜索进入论文视图；非 paper 路径不变 | `webstatic/js/views/paper.js` 经 `app.js` 导入并 `registerView("paper")`；同时**复用注册 `#doc/<id>`**（paper.js 在 document.js 之后导入）——库列表卡片与统一搜索面板现有的 `#doc/<id>` 链接无需改动即可进论文视图；非 paper 直接调用 `renderDocumentRoute(route)`，URL 与行为完全不变。`#paper/<id>` 是显式深链 | `tests/test_papers_view.py::test_paper_view_source_registers_both_routes_and_delegates_non_papers`；Playwright 探针：`#doc/doc-ref-1`→`#work-zone` 可见、`#paper-zone` 隐藏；`#doc/paper-audit`→论文视图 |
| 章节导航树、点击定位、当前节高亮；无 sections 的 paper 回退现行视图 | `paper_view_core.sectionNavItems/buildSectionTree`（level→树/缩进）；点击 `scrollIntoView` + 高亮；IntersectionObserver 维护 `aria-current`。`isPaperView()` 要求 `doc_kind=="paper"` 且有 sections，否则回落 document 视图（`#paper/<id>` 非 paper 时跳 `#doc/<id>`） | `tests/paper_view.mjs` §1/§3；Playwright 探针点击第 5 节→`.paper-nav-link.active=4` |
| 元数据卡片 + 参考文献列表按 SPEC §2 渲染；`resolved_document_id` 可跳转；缺字段不显示占位 | `paper_view_core.paperMetaHtml`（title/authors/year/venue/doi/abstract/keywords/source，空值整行省略）、`referenceListHtml`（仅 resolved 条目渲染 `#doc/<id>` 链接） | `tests/paper_view.mjs` §4–§7；探针 references 3 条 / 1 条 `.paper-ref-link` → `#doc/doc-ref-1` |
| 视觉/可达性基线：正文 ≥14px、辅助 ≥12px、对比度 ≥4.5:1、390px 无横向溢出、audit 3 宽度 0/0/0 | `style.css` 追加独立 P3 区块（不改既有选择器）：正文 14–15px、辅助 12px、`@media (max-width:860px)` 单列；沿用纸感 token | `tests/test_papers_view.py::test_paper_css_meets_the_reading_baseline`（字号 + token 对比度计算）；`scripts/frontend_audit.mjs` 39 checks / 0 findings（含 `paper/paper-audit`、`doc/paper-audit` @1440/768/390，0 溢出/0 裁切/0 pageerror），产物 `/tmp/spw-p3-audit-out/audit.json` |
| 只读消费、`/api/papers/*`；fixture 驱动、不依赖 P1/P2 | 端点只读；测试用自建 fixture/种子记录驱动；未 import `graph2note/papers/*` | `tests/test_papers_view.py` 全部离线 |
| 前端 node 契约 + 后端聚合端点测试离线；全量 pytest 绿 | `tests/paper_view.mjs` + `tests/test_papers_view.py` | 全量 `pytest -p no:warnings` exit 0（**1059 collected**，基线 1048 + 本轮 11~12 项） |

库列表标识：`library_cards.js` 追加式渲染 `.doc-paper-badge`「论文」（`doc_kind` 或 `metadata.doc_kind` 存在时）；当 `/api/documents` 摘要暂不含 `doc_kind` 时，`paper.js` 用只读 `GET /api/papers` 索引 + MutationObserver 兜底给卡片补徽标（幂等）。探针：2 卡 → paper 卡有徽标、普通卡无。

## API 契约（P3 追加，只读）

```
GET /api/papers                -> {"papers":[{"document_id","title","doc_kind"}], "count"}
GET /api/papers/{id}/view      -> {
  "document_id", "doc_kind", "title",
  "meta": {title,authors[],year,venue,doi,abstract,keywords[],source},
  "sections": [{level,title,text,page_start,page_end}],
  "references": [{raw,title,authors[],year,doi,resolved_document_id}]
}   # 不存在 -> 404；非 paper -> doc_kind "" + 空数组（前端回落 document 视图）
```

读取器（`webapp._paper_blob`/`_paper_doc_kind`）容错两种落点：`record["paper"]`（含 `meta/sections/references`）或同级 `paper_meta`/`paper_sections`/`paper_references`；`doc_kind` 取自 `record["doc_kind"]`、`paper["doc_kind"]`，缺失但有 payload 时推断为 `paper`。非法条目跳过、`year` 支持数字字符串、悬空/空字段清空，不抛异常。

## 领地与共享文件

- 独占新文件：`webstatic/js/views/paper.js`、`webstatic/js/paper_view_core.js`、`tests/test_papers_view.py`、`tests/paper_view.mjs`。
- `webapp.py`：只在 `/api/documents/{id}` 之后**追加**独立 `/api/papers/*` 段（+144 行，无既有行改动）。
- `index.html`：`<main>` 内追加 `#paper-zone` 容器（无侧栏入口）。
- `router.js`：追加 `#paper/<id>` 解析 + `subscribeRender`（多观察者，保留 `onRender` 单钩子契约）。
- `state.js`：追加 paper 元素与 ZONES 项。`ui.js`：`NAV_VIEW_ALIAS` 加 `paper:"library"`（1 行）。
- `app.js`：追加 1 行导入 `views/paper.js`（ES 模块入口必需；`test_webapp_layout` 要求所有模块从 app.js 可达）。
- `library_cards.js`：追加 `isPaperDoc`/`paper` 视图模型字段/徽标（既有断言不变）。
- `style.css`：仅末尾追加独立 P3 区块，未改既有选择器。
- `scripts/frontend_audit.mjs`：追加 `AUDIT_EXTRA_ROUTES` 环境变量（默认行为不变）。
- `tests/taxonomy.py`：登记 `test_papers_view→webapp`（`test_taxonomy` 强制要求）。
- **未改** `store.py`/`ir.py`/`diagram*`/`digest.py`/`dashboard.js`/`upload.js`/`papers/*`；未触碰脏文件 `.scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md`。

## 离线 / live 边界（诚实标注）

- **已离线验证**：全部 pytest（1059）、`node tests/paper_view.mjs`（及既有 node 契约）、`/api/papers/*` 三种落点 + 畸形数据 + FileDocumentStore 重载持久化、CSS 基线、`frontend_audit.mjs` 三宽度几何巡检（对手工种子 paper 文档的本地真实服务，未联网、未调 LLM）。
- **未做（留给 reviewer，合并 P1/P2 后）**：真实 P1 论文入库产物 → P2 元数据/参考文献 → 本视图的端到端 live 集成。前轮 P3 `qaRoute` 教训：**必须在 P1/P2 合并后跑真实路由集成**（从库列表/搜索打开真实 paper 文档）。
- 环境无 API key；本 issue 不触网。

## 风险与后续

1. **P1/P2 落点**：若最终把 payload 存到别的键（非 `paper` / `paper_*`），只需扩展 `_paper_blob` 一处；前端只消费 `/api/papers/*`，无需改。
2. **`#doc` 路由覆盖**：paper.js 依赖「在 document.js 之后注册 `doc`」。若后续新增模块在 paper.js 之后再次注册 `doc`，会覆盖论文分发——reviewer 合并时留意 `app.js` 导入顺序。
3. **库徽标**：若 P1 在 `/api/documents` 摘要直接暴露 `doc_kind`，`library_cards` 直接出徽标，`/api/papers` 兜底自动去重（`.doc-paper-badge` 幂等保护）。
4. **DOI**：按「默认不访问外部服务」渲染为纯文本（不生成 doi.org 外链）。
5. **`GET /api/papers` 路径**：与 P1 可能的 `GET /api/papers/{id}` 参数路由不冲突（空段 vs 单段）；`{id}/view` 第二段为字面量，冲突面小。
6. 导航树当前用扁平 `<ol>` + level class 缩进（未递归 `<ol>`），视觉等价、DOM 更简单；如需严格嵌套可改 `sectionNavHtml`。
