# Handoff — Issue 15: 生产链路图形语义提取与重建（FR-009 端到端闭环）

Commits: `f0c1571` — `feat(diagrams): issue 15 — deterministic text-side relation inference + productized visual extractor, FR-009 E2E`
Branch: `dev/15-diagram-extraction` (from `origin/main`)
Status: **in-review** · offline tests **310 passed**

## What shipped

**1) 文本侧图形语义（生产默认路径修复）**
- 新 `graph2note/diagrams/infer.py`（纯确定性，零 live 调用）：
  - `is_relation_line` / `parse_relation_line`：识别 `--> -> => ↔ ← → ←→` 关系，`：/:` 边标签。
  - `infer_flow_from_lines`：节点标签按首次出现去重 → `n1…` id，边引用节点 id（已修复此前标签/ id 混用），`_dedupe_nodes`/`_dedupe_edges` 稳定序。
  - `arrow_flow_block`（连续关系行 run）→ 可解析连 `flow` block（nodes/edges）；不可解析（如 `→ → →`）降级 `diagram` block 且 `caption` 保留原文，**不让任何关系文字丢失**。
  - `detect_diagram_markdown`：文本结构性检出（关系行/图形关键词）。
- `graph2note/vlm.py::_markdown_to_ir`：既有 block 结构**保持不变**（向后兼容），diagram 页额外把**段落与列表项里的 `A → B` 关系**按文档序汇聚为 `flow`/`diagram` block 追加文末。这让真实 VLM 转写的列表式箭头（如 `- Windows → Mac`）也能结构化，IMG01/flowchart 满足 AC1/AC2。

**2) 视觉提取器产品化（独立/opt-in）**
- 新 `graph2note/diagram.py`：`extract_diagram_image`（glm 主提取 trace 原图→严格 JSON nodes/edges）。
  - strict 校验：唯一 id、边引用既有节点、无自环；`{"error":…}` → no_flow。
  - token 升级：空内容 + `finish_reason=length` → **仅一次**升级到 `DIAGRAM_RETRY_TOKENS`（复用 12 经验）；空/解析失败 → degrade verdict，**不重试同参**。
  - cache put/get、惰性加载 `post_gateway`；`resolve_session` 默认 `graph2note-diagram-01`。
- `eval/gateway.py`：新增 `"diagram"` purpose → `graph2note-diagram-01`（issue 14 session isolation 规范）。
- 默认为独立/opt-in，未挂入生产 `parse_document` 主路径（避免逐页第二发 live 调用）；FR-009 闭环按需启用即可。

**3) 渲染/嵌入/降级**：复用 issue-05 附件链（graphviz 主 / matplotlib 回退），表唯一改动；`render.render_markdown` 对 `flow`/`diagram` block 写出 `assets/<doc>-<kind>-<index>.png`；caption-only/无 source 降级写占位图，`missing_attachments == []`。

## Key decisions

- **检测 = 文本结构性**，不做每页 live VLM 分类标注（省调用/确定性）；发现阶段 VLM 已把图形转写为箭头行。
- **默认路径修复 = 确定性箭头推断**（`_markdown_to_ir`），视觉提取器 + 真实转录录制的**离线 golden** 双轨满足 AC1/AC2。
- **保持既有 block 不回退**：追加结构化 block 不删任何文字，golden/既有测试零破坏。
- **edges 引用 node id**（`n1…`）非 label，保证 IR schema 校验通过。

## Verification

- `./.venv-spike3/bin/python -m pytest tests/ spike3/tests/ -p no:cacheprovider` → **310 passed, 7 warnings**（警告均为既有 SWIG/Starlette deprecation，无害）。
- 新增 `tests/test_issue15_diagram.py`（14 条，覆盖 AC1–AC6 + 提取器 fake-gateway/cache 全离线）：
  - AC1：`test_img01_e2e_produces_structured_flow_asset`（注入架构转写）+ `test_img01_authentic_transcription_yields_structured_flow`（**真实 glm 转录已录制 golden** `tests/golden/img01-diagram-stage1.golden.json`，断言 structured flow block + md 嵌入 + `missing_attachments==[]`）。
  - AC2：`test_eval_flowchart_pages_mostly_structured`（6 页 ≥4 structured）。
  - AC3：`test_markdown_to_ir_arrow_chain_becomes_flow` / `..._architecture_text` / `test_non_relation_line_stays_paragraph`。
  - AC4：`test_relation_unparseable_preserves_caption` / `test_degrade_caption_only_block_renders_placeholder` / 提取器 `empty`/`parse_fail` degrade 不重试同参。
  - AC6（FR-020）：`test_flow_render_byte_identical`（同一语义两次重建 PNG 逐字节一致）。
  - 提取器：`test_extract_diagram_image_ok` / `test_extract_diagram_length_exhaustion_upgrades_once`（一次性 10000 token 升级）。
- **Live 验证（预算扣减）**：1 次真实 glm-5.3-flash 转写 IMG01（捕获 stage-1 markdown）+ 1 次全链路 parse（同一转写回放），合计 **2 次 live**（预算 ≤10 达标）。真实转写产生 **3 条 structured flow block**，证明 AC1 是真转录也成立。
- 回归：issue 12 的两阶段链路、e2e images（golden 全 IR cache bypass）、renderer、diagram 渲染链、session isolation / gateway 全绿（后二者按新 `diagram` purpose 同步更新只买了断言集合）。

## Known risks & follow-ups

- 真实手写转写有噪声（重叠箭头 `↓→`、`←→`）会导致少量节点标签不理想（如 `↓`），但结构化与渲染不受影响；如需更干净可后续加 `←→` token 已做 + 对 `↓` 屏蔽，非阻塞。
- 视觉提取器独立/opt-in，尚未接线到默认 parse 主路径；是否默认启用图提取需产品决策（涉及逐页第二发 live 调用与预算）。
- 追加的 flow/diagram block 置文尾（非原位），对「图与说明互引」极端页可能顺序略偏；MVP 下为确定性优先的可接受取舍。
- 无 key/网络依赖；golden 已录制，CI 离线可重复。

## Publishing / notes

- 未修改、未提交任何密钥；`.env` 不上传。
- 本 issue 无远程 provider 任务源（本地 issue tracker，自由实现任务），故不造 PR/MR，仅本地提交 + handoff。