# Spike 1：评估集搭建 + 视觉模型直转质量对比（EditRate）

Status: in-review

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

- 2026-09-08 dispatcher 验收（可自动化部分）：30 页评估集 + 双模型全量报告 + 数据质量复查（1 例并发污染已清除重跑）已合入。**初步选型 glm-3.5-flash**（EditRate 0.77 vs 0.84、30/30 vs 23/30、无截断、延迟减半）——注意 gold 由 glm 草拟存在自评偏置，且字符级 diff 计入标记差异。**最终选型待维护者**：1) gold 人工抽检；2) 补印刷类样本（六类缺一）；3) 确认选型。印刷类缺失与 gold 未校对为剩余 AC。

- 2026-09-08 dispatcher：claimed by graph2note-3（分支 dev/01-spike1-harness）。交付范围 = harness + 2 张现有图冒烟报告；评估集扩充与 gold 校对待维护者。
- 2026-09-08 worker 交付：harness 与冒烟已交付；评估集扩充与 gold 人工校对待维护者（HITL）。

- 交付物：`eval/`（harness + fixtures）、`eval/reports/report-{glm-5.3-flash,deepseek-v4-flash-vision-exp}.md`（真实冒烟报告）、`tests/`（pytest 全绿、离线）。
- 详见交接文档 `../handoffs/01-spike1-vision-quality-eval.md`。
- 当前 gold 为 AI 草拟、未经人工校对，EditRate（~92%–148%）不具选型意义；待维护者补齐评估集（≥30 张，六类目）并人工校对 gold 后用本 harness 重跑。

## 全量评估已跑（2026-09-08，全量批次，merged 网关修复后）

- 评估集已从维护者 4 个多页 PDF 扩到 **30 张**派生页（覆盖五类：手写 10/流程图 6/涂改 6/中英混排 4/公式 4；印刷类缺失——批次无真实打印页）。
- 用修复后生产配置（直出 prompt + 会话固定 + 1024 降采样 + 120s 硬超时）对两模型各跑全量 30 张，缓存复用，全量报告见 `eval/reports/spike1-full-eval-summary.md`。
- **初步选型：倾向 glm-5.3-flash**——样本均值 EditRate 0.7685（vs deepseek 0.8400）、100% 成功（vs 77%，deepseek 7 张 120s 超时）、延迟均值 40s（vs 80s）、无输出截断、无思考型高 reasoning。
- **强警示**：gold 为 AI 草拟（glm），未经人工校对 → glm 偏低有偏、绝对 EditRate 被 Markdown/LaTeX 标记差异抬高（两模型均未达 <5%）；选型结论为样本受限、待人工 gold 校对后复核，**非最终**。
- 数据质量检查：扫描 cache 发现 1 例并发窗口污染（deepseek B11 短补全），已清除并错峰重跑，重跑仍超时，记为失败样本；deepseek 其余短输出为真实截断非污染。
- 涂改类目口径：gold 保留删除段并打 `<<划掉>>` 标，评估 prompt 按语义化删除——该口径差计入编辑，涂改 EditRate 偏高属已知测量差异。
- **HITL 验收依旧**：评估集人工抽检 + gold 人工校对仍待维护者，本 issue 保持 in-review，不 tick 验收项。


