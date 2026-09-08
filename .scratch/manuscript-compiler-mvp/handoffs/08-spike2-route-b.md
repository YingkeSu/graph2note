# Handoff — issue 08（Spike 2 / Route B）

Status: in-review → 交评审。

## 完成内容

- **实现**：`graph2note/ocr.py`（tesseract 封装，never-raise）、`graph2note/route_b.py`
  （`route_b_chain` / `RouteBRouter` / `AutoRouter` / `classify_route_features` / `_looks_like_refusal`）、
  `eval/gateway.py`（新增 `routeb` purpose + `transcribe_text` + `ROUTE_B_*`，默认 session `graph2note-routeb-01`）。
- **运行器**：`scripts/run_route_b_ab.py`（Route A 复用已录缓存零视觉；Route B 走缓存，可多次重跑）、
  `scripts/synth_print_ab.py`（合成印刷样本可复现）。
- **对比报告**：`eval/reports/route-b-ocr-vs-vlm-summary.md`（总体 + 五维表 + 印刷维合成补充 + 策略结论）；
  深层证据 `.scratch/manuscript-compiler-mvp/reports/route-b/`（report.md、scripts/data/*.json）。
- **测试**：新增 `tests/test_route_b.py`、`tests/test_ocr.py`（importorskip 守护）；
  更新 `tests/test_gateway.py`、`tests/test_session_isolation.py`（routeb purpose）。离线全绿 279 / 2 skip。

## 策略结论（已回写 PRD & issue 08）

Route A 在 30 页评估集全面占优（EditRate 0.768 vs 0.865；24/30 页 A 更优；五维逐项均优），**默认恒走 A**；
Route B 仅清印刷 + 纯文本为主（OCR 平均置信度 ≥55）才切（合成清中文印刷 0.114 证明潜能），
公式/符号页与手写页一律 A。`AutoRouter` 默认 A，特征高置信切 B，env 可强制。

## 验证摘要

- 上游 `parse_document(..., router=RouteBRouter(...))` **零改动**可用（route strategy=route_b、Markdown/IR 非空）。
- Route B 全链路 30 页全部产出非空 IR（27/30 structured，3/30 回退原始 OCR），无崩溃。
- OCR/文本失败路径：OCR 空 → 空 IR + warning；文本 LLM 空/拒绝 → 回退原始 OCR。（离线测试覆盖）
- live 文本调用 35 次（≤35：30 页 + 2 合成印刷 + 3 预检），均走 routeb 独立 session。

## 风险与后续

- gold 为 AI 草拟未经人工校对（HITL）；EditRate 绝对值偏高，只能采相对比较。
- 印刷维只有合成样本、Route A 无数据；「Route B 清印刷更优」为单点演示。
- 后续可做 Hybrid（Formula OCR / Fusion / Judge）路由切片。
- 密钥未提交；`.env` 不入库；secret 扫描已跑一路干净。

## 可选：人工复核点

1. 复核 30 页 gold（尤其涂改/删除线保留口径）。
2. 复核「清印刷→Route B」的置信度阈值 55 是否合适（当前仅 2 个合成样本支撑）。
3. 决定是否落地 `AutoRouter` 到产品默认（当前产品仍走 `RouteARouter`，未切换）。