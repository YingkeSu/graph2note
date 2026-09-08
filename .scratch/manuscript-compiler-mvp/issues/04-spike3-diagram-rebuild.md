# Spike 3：流程图语义提取与 matplotlib 重建可行性

Status: claimed

## Parent

[PRD](../PRD.md) Further Notes（Spike 3）；[SPEC](../SPEC.md) FR-009/FR-020 前置验证。

## What to build

验证流程图重建路径是否成立，产出绘图工具链选型结论。端到端行为：`流程图手稿图片 → VLM 提取 nodes/edges 结构语义 → 确定性绘图（matplotlib 或 graphviz）→ 可读图片`。

- 样本从 `test-images/` 起步，用 issue 01 的评估集流程图样本扩充（软依赖）。
- 测试 VLM 对 `A→B、A→C→D`、带分支/回流/标注箭头的手稿能否稳定提取结构语义。
- 分别尝试 matplotlib（自绘/借布局算法）与 graphviz，对比节点重叠、连线交叉、中文标签渲染、输出可复现性。
- 记录语义提取失败率，据此确定「裁剪原图降级」的触发频率预期。

## Acceptance criteria

- [ ] ≥ 10 张流程图手稿完成 nodes/edges 提取试验，成功率与典型失败模式有记录
- [ ] 至少两种绘图方案产出对比样张，给出选型结论（含中文标签与可复现性评价）
- [ ] 同一语义两次绘图输出可复现（满足 FR-020 的确定性要求）
- [ ] 提取失败样本演示裁剪原图降级路径，无乱码输出
- [ ] 结论回写 PRD 开放问题（绘图工具链选型）

## Blocked by

None - can start immediately（样本扩充依赖 issue 01 的图集，非硬阻塞）
