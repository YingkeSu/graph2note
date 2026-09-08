# Spike 2 / Route B：OCR+LLM 路径对比与 Router 策略

Status: ready-for-agent

## Parent

[PRD](../PRD.md)（Recognition Router、Spike 2）；[SPEC](../SPEC.md) SC-005、Recognition Route 实体。**时机：P1——MVP 主链路（issue 01~07）稳定后执行，不阻塞 MVP。**

## What to build

回答「什么时候 OCR 更好」，把 Router 从「恒走 Route A」升级为按文档类型路由。端到端行为：复用 issue 01 的评估 harness，新增 `图片 → 传统 OCR → 文本 LLM 结构化 → IR` 路径，与 Route A 在同集上分维度对比。

- 对比维度：手写体 / 印刷论文 / 公式 / 中英混排 / 小字。
- OCR 引擎选型在此切片内决定（开源本地引擎优先，个人自用本地部署定位）。
- 产出路由策略：何种输入特征（印刷密度、手写比例）走哪条路径；若结论是「Route A 全面占优」，则 Router 保持恒走 A 并记录结论关闭本切片。
- 文本 LLM 环节可使用网关无视觉能力的模型（见 `docs/llm/opencode-go.md` 模型清单）。

## Acceptance criteria

- [ ] Route B 全链路在评估集上可运行并产出指标
- [ ] 五个维度的 A/B 对比表完成，含每类样本量
- [ ] 路由策略结论明确（阈值或规则），回写 PRD；或「Route A 占优」结论成立并有数据支撑
- [ ] Router 接口接入第二种策略后，上游调用方零改动（验证接口设计）

## Blocked by

- 01-spike1-vision-quality-eval（评估集与 harness）
