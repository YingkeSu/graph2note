# 生产链路图形语义提取与重建（FR-009 端到端闭环）

Status: merged

## Parent

[SPEC](../SPEC.md) FR-009（MVP MUST：diagram/flow 携带结构化语义并确定性重建为图片嵌入；失败降级裁原图）、FR-020；[PRD](../PRD.md)「流程图重建进 MVP」决策与 User Story 18。
缺口证据（2026-09-08 维护者实测反馈 + 调度核查）：生产默认路径（issue 12 两阶段：VLM→Markdown→确定性 `_markdown_to_ir`）把 `A → B` 类内容映射为普通段落（实测 block types 无 diagram）；Spike 3 的视觉 nodes/edges 提取停留在 spike3/ 证据阶段未产品化；issue 05 的渲染/附件/降级链完备但无 diagram block 输入。架构图手稿（test-images/01、评估集 flowchart 6 页）当前输出纯文本。

## What to build

把「原图 → 结构化图形语义 → 重建图嵌入」接入生产解析链路。端到端行为：`上传架构/流程图手稿 → 检出图形 → VLM 提取 nodes/edges → diagram/flow block 入 IR → graphviz/matplotlib 重建图落盘 assets → Markdown 图片嵌入 → 三栏 UI 可见`；提取失败 → 裁剪原图降级（已有链路），绝无乱码、解析不失败。

- **检出**：判定页面/区域含流程/架构图语义（候选：VLM 页面分类标注、`_markdown_to_ir` 识别箭头/依赖模式、或评估集 flowchart 类目元数据——实现期定，写明决策）。
- **视觉提取**：spike3 提取器产品化入 `graph2note/`（图片→严格 JSON nodes/edges；glm；独立 purpose session；token 升级策略沿用 12 的经验；空内容→降级不重试同参）。
- **文本侧图形**（低成本补齐）：`_markdown_to_ir` 对 `A → B` 模式行确定性生成 diagram/flow block（nodes/edges 可解析时结构化，否则 caption 保留文字）——覆盖「正文里描述的关系」。
- **渲染嵌入**：复用 05 附件链（graphviz 主/matplotlib 回退，FR-020 确定性）；router 的 degrade source 注入已有。
- **UI 可见性**：三栏预览中图片引用正常渲染（06 已支持附件服务，验证即可）。

## Acceptance criteria

- [x] `test-images/01`（架构图手稿）端到端产出含 nodes/edges 的 diagram block，重建图嵌入 `.md` 与三栏 UI 可见（`test_img01_e2e_produces_structured_flow_asset` 与真实转录 golden `test_img01_authentic_transcription_yields_structured_flow`）
- [x] 评估集 flowchart 6 页中 ≥4 页产出结构化 diagram block（其余走裁图降级，全程无乱码、无失败）（`test_eval_flowchart_pages_mostly_structured` / `test_degrade_caption_only_block_renders_placeholder`）
- [x] 纯文本描述的 `A → B` 关系（无原图图形）也能确定性生成 diagram block（`test_markdown_to_ir_arrow_chain_becomes_flow` / `test_markdown_to_ir_architecture_text`）
- [x] 提取失败样本走裁剪原图降级，端到端不失败（回归）（extractor `empty`/`parse_fail` degrade；caption-only render 回归）
- [x] 离线测试（录制响应/缓存）全绿，CI 无 live 调用；live 验证预算 ≤10 次（产出 310 passed；live 验证使用 cache；img01 真实转录已录制 golden）
- [x] 重建图确定性（同一语义逐字节一致）回归保持（`test_flow_render_byte_identical`；渲染实无改动，沿用 05 链）

## Status note (delivery)

- 全量离线测试 `tests/ spike3/tests/` = **310 passed**（含 issue-15 新增 14 条：`tests/test_issue15_diagram.py`）。
- 交付分支 `dev/15-diagram-extraction` 自 origin/main 创建；提交 `09a6d92`（工作树干净，未 push）。
- 实现边界：检测为**文本结构性**（`_markdown_to_ir` 对关系行确定性汇聚为 flow/diagram block，段落与列表项均可）；视觉提取器已产品化但默认独立/opt-in，未挂入生产 parse 主路径（避免逐页第二发 live 调用），供 FR-009 闭环按需启用。

### 迭代 15c（2026-09-10，main 直提）

- 解除上条边界：视觉提取器作为 **stage-3** 挂入生产 parse 主路径——stage-1 转录检出箭头信号即触发，成功时以一个 page-level graph block 替换文字侧碎片化 flow blocks；任何失败非致命，确定性 Markdown 推断仍为回退。`GRAPH2NOTE_DIAGRAM_MODEL` 可选独立拓扑模型。
- 确定性层升级：单行链式箭头（`输入 → 解析 → 输出`）拆分为连续边；`←` 反向边；`relation_lines` 跨 bullet/heading 边界按页汇聚；Kahn 分层处理环剩余；渲染支持 TB/LR/RL/BT 方向（附件语义透传）；CJK 节点标签 18 单位换行。
- `diagram._post` 改走 `vlm.post_gateway` 缝（产品代码不再 import `eval.gateway`）；`timing.json` 增加 diagram 阶段审计（verdict/model/nodes/edges）。
- 提交：`c9da3c7`（确定性层）+ `57bd686`（stage-3 接线）；离线 `tests/` 295 passed。

## Blocked by

None（所有依赖组件已在 main）
