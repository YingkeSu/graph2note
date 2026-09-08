# 生产链路图形语义提取与重建（FR-009 端到端闭环）

Status: claimed

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

- [ ] `test-images/01`（架构图手稿）端到端产出含 nodes/edges 的 diagram block，重建图嵌入 `.md` 与三栏 UI 可见
- [ ] 评估集 flowchart 6 页中 ≥4 页产出结构化 diagram block（其余走裁图降级，全程无乱码、无失败）
- [ ] 纯文本描述的 `A → B` 关系（无原图图形）也能确定性生成 diagram block
- [ ] 提取失败样本走裁剪原图降级，端到端不失败（回归）
- [ ] 离线测试（录制响应/缓存）全绿，CI 无 live 调用；live 验证预算 ≤10 次
- [ ] 重建图确定性（同一语义逐字节一致）回归保持

## Blocked by

None（所有依赖组件已在 main）
