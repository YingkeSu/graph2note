# 解析提速：基线实测与优化达标

Status: in-review

## Parent

[PRD](../PRD.md) P1 增补（性能预算）；[SPEC](../SPEC.md) FR-025。

## What to build

把单页解析耗时压到可用水平。端到端行为：`分阶段耗时基线报告 → 至少两项优化落地 → 单页端到端 P95 ≤ 60s 且质量不回退`。

- 先测基线：预处理 / LLM 调用 / 渲染分阶段计时（评估集样本），定位主瓶颈并落报告。
- 候选优化路径（按实测选择，至少落地两项）：
  - 非推理或低推理输出模式、prompt 约束 JSON 直出以压 token
  - 预处理与 LLM 调用、多页并行的并发化
  - 同图/同文档缓存（重新解析复用）
  - 图片降采样/压缩后再送视觉模型（在质量不回退前提下）
- 回归门槛：优化后用评估集子集复测，EditRate 与结构指标不劣化。

## Acceptance criteria

- [x] 分阶段基线报告产出（含每阶段 P50/P95 与瓶颈结论）
- [x] 至少两项优化落地，各有前后对比数据
- [x] 单页端到端 P95 ≤ 60s（以评估集样本实测；且远低于预算）
- [~] 优化后评估集子集的 EditRate 不劣化（有对比数据）— **顺延**：产品管线对扫描板书渲染空 IR，无法在 product 路径算 EditRate；正式口径对齐 eval-harness（见 handoff）
- [x] 提速不引入新的失败路径（超时/重试逻辑回归测试通过）

## Blocked by

- 03-parse-pipeline-cli

## Comments

2025-issue11 接管（worker 5，`dev/11-parse-latency`）：基线实测 + O1/O2/O3 落地。
报告见 `reports/latency-baseline.md`；handoff `11-parse-latency-optimization.md`。
要点：after P95≈6.4s（≪60s）、reasoning 28–129、retries=0；O1 vlm↔eval/gateway
收敛，O2 整页结果缓存（重新解析零调用），O3 多页并发；134 passed。EditRate
因 product 渲染空 IR 顺延，Align eval-harness 口径。
