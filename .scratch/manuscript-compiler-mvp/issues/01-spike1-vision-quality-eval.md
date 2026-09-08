# Spike 1：评估集搭建 + 视觉模型直转质量对比（EditRate）

Status: claimed

> 2026-09-08 调度备注：harness 构建与现有样本冒烟已派 agent（graph2note-3）；评估集供图与 gold 人工校对为 HITL，已汇总给维护者，不阻塞交付。

## Parent

[PRD](../PRD.md) — 「三个 Spike 先于功能开发」；[SPEC](../SPEC.md) SC-001/SC-005。

## What to build

搭建评估 harness 并完成第一个质量验证，决定 MVP 的视觉模型选型。端到端行为：

1. 准备 30–50 张真实手稿评估集（手写笔记、印刷扫描、公式、中英混排、流程图样本，含涂改样本；起始素材在 `test-images/`，其余由维护者提供）。
2. harness 以 CLI 运行：`图片 → opencode go 网关视觉模型 → Markdown`，对两个已冒烟验证的候选模型 `glm-5.3-flash` 与 `deepseek-v4-flash-vision-exp` 各跑全量评估集（调用参数见 `docs/llm/opencode-go.md`：`x-opencode-session` 头、`max_tokens=10000`）。
3. gold Markdown 由 AI 辅助标注 + 人工校对（HITL 环节），以 fixtures 形式入库。
4. 计算 EditRate（gold 与输出做字符级 diff，插入/删除/替换折算编辑字符数后归一化）及 Content/Structural Accuracy 抽检记录。
5. 产出选型结论：EditRate 是否达到 < 5% 目标、两模型对比、是否需要引入其他供应商或 OCR 路径。

## Acceptance criteria

- [ ] 评估集 ≥ 30 张，覆盖手写/印刷/公式/中英混排/流程图/涂改六类，gold Markdown 全部经人工校对
- [ ] harness 可一键对指定模型跑全量评估集并输出指标报告
- [ ] 两模型的 EditRate、分类目正确率已列出并给出选型建议
- [ ] 全部 fixtures（图片 + gold + 报告）入库，他人可复现
- [ ] 涂改样本验证语义化删除的表现（明确划掉的内容不输出、模糊的保守保留）有专门记录

## Blocked by

None - can start immediately（图片扩充与 gold 校对需维护者参与）

## Comments

- 2026-09-08 dispatcher：claimed by graph2note-3（分支 dev/01-spike1-harness）。交付范围 = harness + 2 张现有图冒烟报告；评估集扩充与 gold 校对待维护者。
