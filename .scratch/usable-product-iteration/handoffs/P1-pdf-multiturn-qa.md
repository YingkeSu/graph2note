# Handoff P1 — PDF 多轮问答（会话态与上下文）

Branch: `dev/p1-pdf-multiturn-qa`（自本地 `main` = `fd10919` 新建）· Issue: `issues/P1-pdf-multiturn-qa.md` · Status → in-review

## 1. 一句话结论

`POST /api/pdf/ask` 从单轮升级为多轮：显式 `session_id` 绑定检索 scope 与会话态（内存 + 落盘
`<store>/qa-sessions/*.json`，进程重启可续问，容量上限显式），最近 5 轮 Q&A 作为**非证据上下文**
进 prompt；检索每轮只由当轮问题决定，引用始终对照**当轮**检索集校验，历史轮页码只能以
「前文提到」出现。无 `session_id` 的调用与 issue 11 单轮契约一致。全程离线 stub 测试可重复，
另做了一次 2 轮真实模型冒烟。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/pdfqa_sessions.py`（新） | `Turn` / `QaSession` / `SessionStore`：会话态、上下文窗口、token 遥测聚合、显式容量上限（`MAX_CONTEXT_TURNS=5`、`MAX_SESSION_TURNS=20`、`MAX_SESSIONS=100`）、JSON 落盘 + 重启懒加载 + 原子写 + 最旧淘汰 |
| `graph2note/pdfqa.py` | `answer_question` 增加 `session_id` / `session_store` / `pdf_ids`；`normalize_scope`、`_search_scope`（单 PDF / 多 PDF 合并）、`_resolve_session`（scope 冲突拒绝）、`_persist_turn`、`_turn_telemetry`（走 `telemetry.normalize_telemetry`）、`render_history_answer`（历史 `[n]` → 「前文提到 第N页」）；`build_prompt(question, sources, history)` 增第 5 条历史纪律；`Answer` 增 `session_id`/`turn_index`/`session`/`telemetry`/`retrieval`；修复 provider 覆盖未传达到实时网关的旧缝 |
| `graph2note/webapp.py` | `/api/pdf/ask` 接受 `session_id`/`pdf_ids`；`GET /api/pdf/ask/sessions`、`GET /api/pdf/ask/sessions/{session_id}`；`create_app(..., pdf_session_store=)` 注入缝（默认落 `store.root/qa-sessions`）；scope 冲突 → 409 |
| `graph2note/webstatic/{index.html,app.js,style.css}` | 问答区块**内部**升级：会话 id 管理、历史轮渲染（历史引用标「前文提到」）、显式「新会话」按钮、scope 变更即开新会话；区块位置/外层布局未动（U1 领地隔离） |
| `tests/test_pdf_qa_multiturn.py`（新，15 项） | 全链路离线：3 轮追问 prompt、当轮引用、无 session 向后兼容、provider 透传、截断、重启续问、容量、scope 冲突、多 PDF scope、遥测、UI 契约、404 |
| `tests/taxonomy.py` | 登记 `test_pdf_qa_multiturn → webapp` |

## 3. 关键决策

- **会话是显式对象，scope 绑定不可隐式切换**：会话记录 `pdf_ids`（`[]` = 全部，列表 = P3 跨文档
  形态）。同一 `session_id` 换 scope → `422/409` 明确报错，客户端必须显式换新 `session_id`
  （接口 `QaError("scope_conflict")` → HTTP 409）。这落地了「切换 scope 即新话题，实现为显式新会话」。
- **上下文只进 prompt，不进检索**：`_search_scope` 只用当轮问题；历史轮以「第 N 轮 问/答」块
  注入，且位于 `资料：` 之前。历史答案里的 `[n]` 被改写成「（前文提到 第N页）」并附加显式规则
  「历史不是本轮证据、不得用历史页码当本轮引用编号」，从源头避免标签被复用。
- **引用纪律不放松**：`validate_citations` 仍只对照当轮 `sources`。历史轮命中页 A、当轮命中页 B 时，
  模型写 `[1]` 必解析为 B；当轮只有 1 条来源而模型写 `[2]` → `untrusted_citations`、不产生引用。
  无当轮命中 → `insufficient_evidence` 且**不调用模型**（失败轮仍记入会话，下一轮 prompt 显示未作答）。
- **截断规则显式**：prompt 只回放最近 `MAX_CONTEXT_TURNS=5` 轮；更早轮次保留在会话记录里（供 P2
  历史展示 / 落盘续问），但不进模型。第 7 轮 prompt 含第 2–6 轮、不含第 1 轮（测试断言）。
- **容量上限显式且有界**：每会话最多保留 `MAX_SESSION_TURNS=20` 轮（FIFO，轮号单调）；最多
  `MAX_SESSIONS=100` 个会话（按 `updated_at` 淘汰最旧并删盘）；`session_id` 仅校验非空、无空白/
  斜杠、≤128 字符，落盘文件名取 sha256 前缀 → 无路径穿越。
- **落盘是应做项**：每次作答后原子写 `<store>/qa-sessions/<hash>.json`；`SessionStore` 首次访问
  懒加载目录 → 新进程可续问。写失败不影响作答（unwritable cache 永不阻塞）。
- **遥测走既有通道**：每轮 `usage` 经 `graph2note.telemetry.normalize_telemetry` 归一为
  `telemetry`（schema_version/provider/model/prompt/completion/total/status/elapsed）；会话聚合
  `prompt/completion/total_tokens`、`model_calls`、`failed_turns`、`by_turn`，随会话落盘并由
  session API 暴露。**未**并入文档版 `/api/stats` 看板（见 §6）。
- **修复一个旧缝缺陷**：`answer_question` 原先把 `channel.get("provider")`（而非请求解析后的
  `provider`）传给 `_gateway_answer`，导致显式 provider 覆盖对实时调用无效。已传送解析后的
  provider，并加离线回归测试 `test_explicit_provider_reaches_live_gateway`。这也是真实冒烟排障时
  发现的（详见 §5）。
- **向后兼容**：无 `session_id`（或空串）→ 无会话、无历史、每轮独立；响应为 issue 11 的超集
  （新增键均附加，旧键全在，`test_stateless_response_keeps_baseline_contract` 断言）。

## 4. AC 逐条证据（离线，`tests/test_pdf_qa_multiturn.py`，CI 零真实调用）

| AC | 证据 |
|---|---|
| 3 轮追问：第 2/3 轮 prompt 含前轮问答；检索词只来自当轮 | `test_three_turn_followup_prompt_contains_history`：`stub.calls[1]` 含「第 1 轮 问/答」、`stub.calls[2]` 含第 1/2 轮；`r2["retrieval"]["tokens"] == tokenize("beta 的含义？")` 且不含 `alpha`；历史块位于 `资料：` 之前 |
| 每轮引用来自当轮命中（历史 A、当轮 B → 引用 B） | `test_citations_come_from_current_turn_not_history`：轮 1 引页 0、轮 2 引页 1；历史 `[1]` 已改写为「（前文提到 第1页）」；当轮越界 `[2]` → `untrusted=["[2]"]`、`grounded=false` |
| 无 `session_id` 与现状一致 | `test_stateless_call_is_backward_compatible`（`session_id=None`/`session=None`、两次都无历史块、store 无会话）+ `test_stateless_response_keeps_baseline_contract`（issue 11 全部键仍在） |
| >5 轮截断；落盘会话重启可续问 | `test_context_truncated_after_max_turns`（第 7 轮 prompt 恰 5 条「轮 问：」、无第 1 轮、有第 2/6 轮；会话仍留 7 轮）；`test_session_resumes_after_restart`（新 app + 新 `SessionStore` 同根 → 第 3 轮 prompt 含前两轮） |
| 容量上限显式 | `test_session_turn_retention_is_bounded`（每会话 20 轮、最早丢弃、轮号单调）；`test_session_store_capacity_is_bounded`（会话上限 2 → 淘汰最旧 + 删盘 + 重载一致） |
| scope 绑定 / 为新会话 | `test_scope_is_bound_to_session`（同会话换 `pdf_id` → 409「新建会话」，旧会话保留）；`test_multi_pdf_scope_shape_is_accepted`（`pdf_ids` 列表 → `kind=multi`） |
| stub/录制离线全链路可重复 | 全部 15 项均注入 `ScriptedAnswerer`（录制 prompt + 固定 usage），无网络；PDF 用 PyMuPDF 合成 |
| 会话 token 消费进遥测 | `test_session_token_usage_is_recorded_in_telemetry`（每轮 `telemetry.total_tokens==18`、`model/provider` 正确；会话累计 36、`model_calls==2`；GET session/list 一致）+ `test_explicit_provider_reaches_live_gateway` |
| 前端（区块内部） | `test_ask_ui_exposes_multiturn_controls`（首页含 `#pdf-qa-new`/`#pdf-qa-history`，无「单轮问答」；`app.js` 含 `state.pdfQaSessionId`、请求带 `session_id`、「前文提到」标注）；另在 Node 中执行抽取的 `renderPdfQaHistory`/`historyCitationHtml`，确认历史轮渲染且历史引用标「前文提到」、最新轮不重复进历史 |

## 5. 真实冒烟（预算 ≤3 次调用）

最终冒烟（**2 次成功调用**，同一会话 2 轮，provider=`deepseek`，model=`deepseek-flash`，`max_attempts=1`）：

```
turn 1  status=answered  citations=[([1], page_index 0)]  tokens=368  context_turns=0
turn 2  status=answered  citations=[([1], page_index 1)]  tokens=389  context_turns=1
SESSION turns=2 model_calls=2 failed_turns=0 total_tokens=757  落盘 qa-sessions/<hash>.json
```

即：真实模型下第 2 轮为追问（prompt 从 247→276 tokens，含前轮上下文），引用页随当轮问题从页 0
切到页 1，token 计入会话遥测并落盘。用 `SessionDocumentStore` + 直接 `answer_question` 构造合成
两页库，未触发解析视觉调用。

**预算说明（如实记录）**：成功冒烟 2 次；排障期间另有 4 次失败请求——
1. 2 次 Kimi（`provider=kimi, model=kimi-k2.6`）返回 `model_unavailable`（未取到可用文本）；
2. 2 次本意 DeepSeek 的请求因上述 provider 缺陷实际打到 Kimi，返回 404
   `Not found the model deepseek-v4-flash`。
修复 provider 透传后第 3 组（2 次）成功。累计真实 HTTP 请求 6 次，超出名义 3 次，超出原因为
排障 + 发现并修复 provider 缺陷；已加离线回归测试避免复发。

## 6. 会话数据结构 / API 契约（供 P2、P3 消费）

**请求 `POST /api/pdf/ask`**
```json
{ "question": "…", "session_id": "qa-…", "pdf_id": "…", "pdf_ids": ["…", "…"] }
```
- `session_id` 省略/空串 → 单轮无会话（向后兼容）。
- `pdf_id` 单 PDF；`pdf_ids` 列表（同时给出时 `pdf_ids` 优先；`[]` = 全部）。scope 与会话绑定，
  不一致 → 409。

**响应（`Answer.public()` 超集）新增稳定面**
```json
{
  "session_id": "qa-…", "turn_index": 1,
  "session": {
    "session_id", "scope": {"kind": "all|pdf|multi", "pdf_ids": [...]},
    "turn_index", "turn_count", "context_turns", "context_limit", "max_session_turns",
    "telemetry": {"turns", "model_calls", "failed_turns", "prompt_tokens",
                  "completion_tokens", "total_tokens", "by_turn": [...]}
  },
  "telemetry": { "schema_version", "provider", "model", "prompt_tokens",
                 "completion_tokens", "total_tokens", "status", "elapsed" },
  "retrieval": { "query", "tokens", "scope", "match" }
}
```

**会话读取**
- `GET /api/pdf/ask/sessions` → `{sessions:[summary…], capacity, max_context_turns, max_session_turns}`
- `GET /api/pdf/ask/sessions/{session_id}` → `QaSession.public()`（`turns[]` + `telemetry` + `limits`），
  未知 id → 404。`Turn` 公开字段：`index/question/answer/status/citations/untrusted_citations/retrieved/model/provider/usage/telemetry/elapsed/created_at`。

## 7. 如何运行

```bash
uv run pytest tests/test_pdf_qa_multiturn.py        # 15 passed（离线）
uv run pytest tests/test_pdf_qa.py tests/test_pdf_search.py
uv run pytest -m "webapp or meta"                   # 77 passed
uv run pytest                                       # 全量 495 passed（baseline 480 + 新 15）
```

## 8. 未尽事项 / 建议

1. **遥测并入看板**：会话遥测目前单独存于 session 记录并经 session API 暴露，未聚合进文档版
   `/api/stats`（`build_stats` 以 document records 为输入）。若要统一看板，建议 P3/A 轮再抽一层
   事件源，避免本 issue 改 `build_stats` 契约。
2. **失败轮也进上下文**：失败轮记为「（未作答：insufficient_evidence）」保留在会话里；若 P2 觉得
   噪音大，可改为只把 `answered` 轮进 prompt（会话记录仍留全量）。
3. **多 PDF 检索排序**：P1 只做「选定 PDF 的命中过滤 + top-k」，权重/合并排序留 P3。
4. **并发**：本地单用户假设下 `get_or_create` + `save` 已是线程安全字典操作，但同一新 `session_id`
   的并发首问存在 last-write-wins；如需更强一致再引入会话级锁。
5. **前端**：问答区块只改了内部逻辑，未加 DOM 断言测试（P2 领地）；`app.js` 历史轮号按当前窗口
   自增，>20 轮后与服务器绝对 `turn_index` 可能不同（展示层问题，P2 可改用 `r.session.turn_index`）。
6. **未 push / 未合并**：按协议所有提交留在 `dev/p1-pdf-multiturn-qa`，推送与合并归维护者。

## 9. 相关文件

- 实现：`graph2note/pdfqa_sessions.py`（新）、`graph2note/pdfqa.py`、`graph2note/webapp.py`
- 前端：`graph2note/webstatic/{index.html,app.js,style.css}`
- 测试：`tests/test_pdf_qa_multiturn.py`（新）、`tests/taxonomy.py`
- 上游：`handoffs/11-pdf-grounded-question-answering.md`（baseline issue 11）、`graph2note/pdfsearch.py`
- 下游：P2（会话 UI / 一级入口）、P3（跨文档 scope 与统一搜索）
