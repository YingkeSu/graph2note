# Handoff P2 — 问答对话式界面与一级入口

Branch: `dev/p2-qa-conversation`（自本地 `main` = `63ffd0b` 新建；含 `merge: U1` 与 `merge: P1`）
Issue: `issues/P2-qa-conversation-ui.md` · Status → in-review

## 1. 一句话结论

PDF 问答从 Library/临时 `#pdf-search` 区块升级为侧栏一级视图 `#ask`：scope 选择（默认全部已导入
PDF）+ 气泡对话区（用户右 / 助手左）+ 显式「新会话」+ 历史会话列表。助手气泡内嵌引用芯片
`[PDF 名 · p12]`，点击打开原 PDF 页（沿用既有 `/api/documents/<id>/source-page` 跳转路径）。
会话 id 落 `localStorage` 并在刷新后按 P1 落盘恢复（无本地记录时续最近一段会话）；等待态是**当轮
气泡**而非全屏阻断，错误只重发当轮。PDF 关键词检索入口原样挂载为本视图的辅助工具条（`<details>`），
未重构其内部逻辑，P3 无需改 pdfsearch 前端。全程离线 stub 测试，CI 零真实 LLM 调用。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/webstatic/js/ask_core.js`（新，纯函数） | `buildAskPayload`（`session_id` 持续携带 + 可选 `pdf_id`）、`citationName/citationPage/citationLabel/citationChipHtml`（`[PDF 名 · p12]` 芯片 + `source_page_url` 跳转 + `#doc/<id>` 校对链接）、`normalizeTurn/turnFromResponse/sessionToTurns`、`userTurnHtml/pendingTurnHtml/errorTurnHtml/assistantTurnHtml/renderConversationHtml`、状态词表。零 DOM/零 import，Node 可直接单测 |
| `graph2note/webstatic/js/views/ask.js`（新） | 一级视图：scope `<select id="pdf-qa-scope">`、新会话按钮、气泡渲染、历史会话列表、P1 会话恢复（`localStorage["graph2note.askSessionId"]` → `GET /api/pdf/ask/sessions/{id}`；缺失时续最近一段）、等待/错误/重试（只重发当轮）、跨视图入口契约（见 §6） |
| `graph2note/webstatic/index.html` | 侧栏 `nav-pdf-search` → `nav-ask`（`data-route="#ask"`）；`#pdf-search-zone` → `#ask-zone`（scope + 对话区 + 新会话 + 历史列表）；关键词检索 `#pdf-search` 原样迁入 `#ask-zone > <details id="ask-search-toolbar">` |
| `graph2note/webstatic/js/views/pdf.js` | 移除问答逻辑（归 `ask.js`），保留上传/逐页任务 + 关键词检索；`loadPdfScopeOptions(selectEl)` 参数化并导出 |
| `graph2note/webstatic/js/state.js` | 元素注册（`askZone/askScope/askEmpty/askSessions…`）、`state.askSessions/askBusy`、`ZONES` 以 `askZone` 替代 `pdfSearchZone` |
| `graph2note/webstatic/js/router.js` | 新增 `#ask`；`#pdf-search` 作为**兼容别名**仍指向 ask 视图（U1 书签 / P3 面板不用改路由） |
| `graph2note/webstatic/app.js` | 入口 import `./js/views/ask.js` |
| `graph2note/webstatic/js/ui.js` | 全局搜索占位提示文案改为「问答」视图（1 行） |
| `graph2note/webstatic/style.css` | `.ask-*` 气泡/芯片/等待/错误/空态/历史列表/辅助工具条样式；移除旧 `.pdf-qa-*`（逻辑已迁 ask_core） |
| `tests/test_ask_view.py`（新，7 项） | DOM 断言（一级入口 / scope / 对话区 / 新会话 / Library 不承载问答 / 辅助检索保留）+ 前端行为源断言 + `node tests/ask_view.mjs` + stub answerer 三轮 API mock |
| `tests/ask_view.mjs`（新） | 纯函数契约：3 轮 payload 同 `session_id`、每轮引用独立、芯片 `[PDF 名 · pN]` + `source_page_url`、等待/错误/重试 HTML、响应映射 |
| `tests/test_webapp_layout.py` / `tests/router_routes.mjs` | U1 断言适配新布局（`pdf-search-zone` → `ask-zone`；`#pdf-search` → `{name:"ask"}`），语义未放宽 |
| `tests/test_pdf_qa_multiturn.py` | P1 的 UI 契约测试适配 P2 视图（`#pdf-qa-new/#pdf-qa-history/#ask-zone` 仍在；旧的「前文提到」分栏标注改为 ask 视图的逐轮引用芯片；其余 14 项 P1 后端断言未动） |
| `tests/taxonomy.py` | 登记 `test_ask_view → webapp` |
| `.scratch/usable-product-iteration/evidence/` | `ask-before.png`（main `#pdf-search` 临时入口）、`ask-after.png`（`#ask` 一级视图 + 3 轮气泡 + 引用芯片，均 `graph2note visual-qa capture`，1440×1000）、`ask-layout-metrics.json`（headless DOM 前后量测） |

## 3. 关键决策

- **视图归属与路由**：新一级视图 `#ask`；`#pdf-search` 保留为别名并渲染 ask 视图（`parseHash` 同时
  映射到 `ask`）。这样 U1 的书签与 P3 面板现有的 `go("#pdf-search")` 不需要改就落到新视图。
- **问答与关键词检索分家但同屏**：问答逻辑移入 `ask_core.js` + `ask.js`；搜索逻辑留在 `pdf.js`，
  `#pdf-search` 表单/结果 DOM **原样**搬进 `#ask-zone` 的 `<details>` 辅助工具条，仅把
  `loadPdfScopeOptions` 参数化。**未重构 pdfsearch 内部**，避免与 P3 抢同一文件。
- **会话恢复双层**：优先 `localStorage["graph2note.askSessionId"]` → `GET sessions/{id}`（刷新/重启
  消费 P1 落盘）；本地无记录时续 `GET /sessions` 的最近一段（本地单用户工具，避免重启后静默丢对话）。
  「新会话」只生成新 `session_id` 并清空当前气泡，**从不删除**旧会话（历史列表仍在）。
- **scope 绑定沿 P1**：scope 变更即显式新会话（P1 的 `409 scope_conflict` 语义）；请求体 `pdf_id`
  仅在有选中 PDF 时携带，省略即「全部」。
- **等待/错误按轮呈现**：进行中的当轮渲染为 `ask-pending` 气泡（spinner +「正在检索并生成…」），
  输入框保持可编辑、仅禁用提交按钮；失败轮渲染为 `ask-turn-error` 气泡 +「重试本轮」，
  重试只重发该轮问题（不重发其它轮）。空态 `#ask-empty` 明确引导。
- **引用芯片与跳转**：`[pdf_name || title || document_id · pN]`（title 若是 `"x · 第N页"` 会去掉页
  后缀避免重复），`href` 取 `source_page_url`（既有原页跳转路径，新标签打开），另附 `#doc/<id>`
  「打开校对」。每轮芯片只来自该轮 `citations`，不复用历史轮。
- **P1 前端分栏被气泡取代**：旧实现把「历史轮」与「本轮结果」分两块、历史引用标「前文提到」；
  气泡 UI 让每轮自带引用，因此该标注不再需要（P1 handoff §8.5 已预告此为展示层问题）。

## 4. AC 逐条证据（离线）

| AC | 证据 |
|---|---|
| 问答为侧栏一级视图（scope / 对话区 / 新会话）；Library 不承载问答表单；截图前后对比 | `tests/test_ask_view.py`：`test_ask_is_first_class_sidebar_view`（`nav-ask` 在 `#sidebar-nav`，`nav-pdf-search` 消失）、`test_ask_zone_owns_scope_conversation_and_new_session`（`#pdf-qa-scope` 默认空=全部 / `#pdf-qa-form` / `#pdf-qa-input` / `#pdf-qa-new` / `#pdf-qa-history` / `#ask-empty` / `#ask-sessions`）、`test_library_and_old_zone_do_not_host_qa`；截图 `ask-before.png` → `ask-after.png`；`ask-layout-metrics.json`：`sidebar_ask_entry false→true`、`library_hosts_qa_form false→false`、`ask_zone_hosts_qa_form false→true`、`citation_chips 0→3` |
| 引用芯片点击跳转对应 PDF 原页（DOM 断言 + API mock） | `tests/ask_view.mjs`：`citationChipHtml` 产出 `class="ask-citation"` `href="/api/documents/d1/source-page"` `target="_blank"` `data-document-id`；`tests/test_ask_view.py::test_api_mock_three_turn_session_and_source_page` mock API 断言 `citations[0].source_page_url == /api/documents/<id>/source-page`；headless DOM 实测 3 个芯片 href 均为对应 `source-page`（见 §5） |
| 刷新恢复会话；新会话开空会话、旧会话不删 | `ask.js` `restoreOrStart`：`localStorage["graph2note.askSessionId"]` → `loadSession`；`newSession` 仅换 id/清空气泡；`tests/test_ask_view.py::test_api_mock_three_turn_session_and_source_page`（`GET /sessions/{sid}` 恢复 3 轮；再开新会话后 `GET /sessions` 同时列出两者）；headless 实测刷新后 3 轮气泡+3 芯片；CDP 实测「新会话」后气泡清空、`#ask-sessions` 仍列 3 段会话 |
| 3 轮请求组装同 P1 契约（`session_id` 持续）；每轮引用独立 | `tests/ask_view.mjs`：3 轮 `buildAskPayload` 的 `session_id` 全等、无 `pdf_id` 时省略；`renderConversationHtml` 逐轮分组断言 turn1/2/3 各自芯片与 `source_page_url` 不串；`test_api_mock_three_turn_session_and_source_page`：真实 `POST /api/pdf/ask` 三轮同 sid、`turn_index=[1,2,3]`、`page_index=[0,1,2]` |
| 等待/错误/空状态明确；错误重试只重发当轮 | `tests/ask_view.mjs`：`pendingTurnHtml`（`ask-pending` + 正在检索并生成）、`errorTurnHtml`（`data-ask-retry="2"` + 重试本轮、无引用）、空态 `#ask-empty`（DOM 测试）；`ask.js`：`sendTurn(turn)` 失败置 `status="error"`，`retryTurn(index)` 仅对命中轮调用 `sendTurn`；`submitQuestion` 在 `state.askBusy` 时拒绝并发 |
| 离线 DOM 断言测试覆盖主路径；CI 无真实 LLM | `tests/test_ask_view.py`（7 项）+ `tests/ask_view.mjs`（纯函数）+ headless DOM/DOM stub；stub `ScriptedAnswerer`、合成 PDF，零网络。全量 `uv run pytest`：**619 passed**（含 Node 子测） |

## 5. 真实渲染冒烟（离线，两个 headless 实例）

同一 seed（1 个 3 页合成 PDF + `ScriptedAnswerer`，`qa-evidence-3turn` 预置 3 轮）：

- **before**（main `29c915b`，`#pdf-search`）：`nav-pdf-search` 在侧栏、`pdf-search-zone` 承载 `pdf-qa-form`、`citation_chips=0`。
- **after**（`dev/p2-qa-conversation`，`#ask`）：`nav-ask` 在侧栏、`ask-zone` 承载问答 + 关键词辅助工具条、`citation_chips=3`。
  headless `--dump-dom` 实测 3 个芯片：`[qa · p1] → /api/documents/…-p001/source-page`、`[qa · p2] → …-p002…`、`[qa · p3] → …-p003…`。
- **交互**（CDP `Runtime.evaluate`，真实页面）：`#pdf-qa-new` 清空气泡后 `#ask-sessions` 仍列 3 段；
  表单 submit 后 `#pdf-qa-status = 第 1 轮 · 已生成 · 检索 1 条 · stub-model`，气泡出现 `[qa · p3]` 芯片
  （`target="_blank"`）。注：本机 AO Browser 面板的合成 click/keypress 无法送达页面（P3 handoff §6 已记录同类现象），
  故交互以 CDP 直驱 + 离线 Node/DOM 测试为准。

## 6. 跨视图入口契约（P3「就这些结果提问」消费）

**规范入口（推荐）** —— `graph2note/webstatic/js/views/ask.js` 导出：

```js
// question: string；navigate 默认 true（同时切到 #ask）
export function prefillAsk(question, { navigate = true } = {}) -> boolean
```

同步提供：

```js
// window 事件（模块间解耦，P3 的 search-panel.js 可直接 dispatch）
window.dispatchEvent(new CustomEvent("graph2note:ask",
  { detail: { question: "...", navigate: true } }));

// 经典脚本 / 调试用全局 API
window.__g2nAsk = { prefillAsk, newSession, applyPendingAsk, getSessionId, route: "#ask" };
```

**兼容入口**：`sessionStorage["graph2note.pendingAsk"]`（P3 现行实现）：ask.js 在进入视图与
`hashchange` 时读取并预填 `#pdf-qa-input`、随后清除；`#pdf-qa-input` 这个 id 保留不变。
因此 P3 rebase 后**零改动**即可继续工作：其 `writePendingAsk` + `go("#pdf-search")` 会落到 ask 视图
并预填；若要显式调用，建议改用 `prefillAsk` 或 `graph2note:ask` 事件。

## 7. 如何运行

```bash
uv run pytest tests/test_ask_view.py tests/test_webapp_layout.py tests/test_pdf_qa_multiturn.py
node tests/ask_view.mjs
node tests/router_routes.mjs
uv run pytest -m webapp
uv run pytest                 # 全量 619 passed in 101.29s（离线）
```

## 8. 未尽事项 / 已知边界

1. **历史会话列表是加分项，已做**：`GET /api/pdf/ask/sessions` 列表 + 点击载入；无删除入口（删除会话
   不在 issue 范围）。
2. **多选 PDF scope 未做**：issue 只要求 scope 选择（默认全部），单 `pdf_id` 或全部；`pdf_ids` 多选
   留给 P3 的跨文档形态，前后端契约已兼容。
3. **引用 PDF 名在 main 上退化为文档标题**：P1 引用 payload 无 `pdf_name`，本视图取 `title` 并去掉
   `"· 第N页"` 后缀 → `[qa · p1]`；P3 合入后 `pdf_name` 会被优先使用 → `[qa.pdf · p1]`。
4. **`#pdf-search` 为兼容别名**：P3 落地统一搜索面板后，可把别名/辅助工具条收敛为一个入口；
   当前保留以保证并行期不破坏 P3 的跳转。
5. **未 push / 未合并 main / 未自审**：提交留在 `dev/p2-qa-conversation`，推送与合并归维护者；
   未改 `BOARD.md` 与 `issues/*.md`。
6. **未改 pdfsearch 内部**：`pdf.js` 仅移出问答与参数化 scope 加载；`#pdf-search` 表单/结果 DOM 原样
   挂在 ask 视图的 `<details>` 里，`runPdfSearch`/`renderSearchHits` 行为不变。

## 9. 相关文件

- 实现：`graph2note/webstatic/js/ask_core.js`（新）、`graph2note/webstatic/js/views/ask.js`（新）、
  `graph2note/webstatic/{index.html,app.js,style.css}`、`graph2note/webstatic/js/{state.js,router.js,ui.js,views/pdf.js}`
- 测试：`tests/test_ask_view.py`（新）、`tests/ask_view.mjs`（新）、`tests/test_webapp_layout.py`、
  `tests/router_routes.mjs`、`tests/test_pdf_qa_multiturn.py`、`tests/taxonomy.py`
- 证据：`.scratch/usable-product-iteration/evidence/ask-{before,after}.png`、`ask-layout-metrics.json`
- 上游：`handoffs/P1-pdf-multiturn-qa.md`（会话 API 契约）、`handoffs/U1-global-layout-navigation.md`（骨架与挂载点）
- 下游：P3（统一搜索面板消费 §6 入口；`handoffs/P3-cross-doc-unified-search.md` §7 的 U1 适配步骤仍然适用，
  另需注意问答视图已从 `#pdf-search` 变为 `#ask`（兼容别名仍可用））
