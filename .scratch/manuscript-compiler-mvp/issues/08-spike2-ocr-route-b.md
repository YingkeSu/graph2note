# Spike 2 / Route B：OCR+LLM 路径对比与 Router 策略

Status: merged

## Parent

[PRD](../PRD.md)（Recognition Router、Spike 2）；[SPEC](../SPEC.md) SC-005、Recognition Route 实体。**时机：P1——MVP 主链路（issue 01~07）稳定后执行，不阻塞 MVP。**

## What to build

回答「什么时候 OCR 更好」，把 Router 从「恒走 Route A」升级为按文档类型路由。端到端行为：复用 issue 01 的评估 harness，新增 `图片 → 传统 OCR → 文本 LLM 结构化 → IR` 路径，与 Route A 在同集上分维度对比。

- 对比维度：手写体 / 印刷论文 / 公式 / 中英混排 / 小字。
- OCR 引擎选型在此切片内决定（开源本地引擎优先，个人自用本地部署定位）。
- 产出路由策略：何种输入特征（印刷密度、手写比例）走哪条路径；若结论是「Route A 全面占优」，则 Router 保持恒走 A 并记录结论关闭本切片。
- 文本 LLM 环节可使用网关无视觉能力的模型（见 `docs/llm/opencode-go.md` 模型清单）。

## Acceptance criteria

- [x] Route B 全链路在评估集上可运行并产出指标（30 页全部产出非空 IR；明细 `reports/route-b/scripts/data/ab_summary.json`）
- [x] 五个维度的 A/B 对比表完成，含每类样本量（`eval/reports/route-b-ocr-vs-vlm-summary.md`；印刷维滑真实样本=0，用合成印刷样本补 Route B，方法已documented）
- [x] 路由策略结论明确（规则）且回写 PRD；默认恒走 Route A（数据支撑），清印刷高置信才走 Route B
- [x] Router 接口接入第二种策略后，上游调用方零改动（RouteBRouter/parse_document 验证）

## Deliverables（随分支提交）

- 实现：`graph2note/ocr.py`（tesseract 封装，never-raise）、`graph2note/route_b.py`（`route_b_chain` / `RouteBRouter` / `AutoRouter` / `classify_route_features`）、`eval/gateway.py`（新增 routeb purpose 与 `transcribe_text`/`ROUTE_B_*`）
- 运行器：`scripts/run_route_b_ab.py`（A 复用缓存零视觉；B 走缓存，可用于快）、`scripts/synth_print_ab.py`（合成印刷样本复现）
- 对比报告：`eval/reports/route-b-ocr-vs-vlm-summary.md`（总体 + 五维表 + 印刷维合成补充 + 策略结论）
- 离线测试：`tests/test_route_b.py`、`tests/test_ocr.py`（importorskip 守护）、`tests/test_gateway.py`/`tests/test_session_isolation.py`（routeb purpose）
- 证据：`reports/route-b/scripts/data/ab_summary.json`、`synth_print_summary.json`（synth 图片已 gitignore）

## 实测结论（live，文本调用 35≤35）

Route A 在 30 页评估集全面占优：EditRate 0.768 vs 0.865，24/30 页 A 更优，五维逐项均优。清中文印刷（合成 SYN-P1）Route B 达 0.114，证明其窄适用区间。


## Blocked by

- 01-spike1-vision-quality-eval（评估集与 harness）
