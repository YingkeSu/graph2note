# 视觉模型评估报告（Spike 1 — glm-5.3-flash）

- 生成时间: 2026-09-08 05:39:58 UTC
- 模型: `glm-5.3-flash`
- 样本数: 2
- ⚠️ **2 份 gold 为 AI 草拟、未经人工校对（HITL 待维护者）**

## 总体 EditRate

- 样本均值 EditRate: **1.1971** (119.71%)
- 聚合 EditRate（Σ编辑字符 / Σgold 字符）: 1.2313 | Σ编辑字符 676 / Σgold 字符 549
- 目标: < 5.0% (SC-001)

## 分类目指标

| category | label | count | mean_edit_rate | min_edit_rate | max_edit_rate | unproofed_gold |
|---|---|---|---|---|---|---|
| handwriting | 手写笔记 | 0 | — | — | — | 0 |
| print | 印刷扫描 | 0 | — | — | — | 0 |
| formula | 数学公式 | 0 | — | — | — | 0 |
| mixed | 中英混排 | 0 | — | — | — | 0 |
| flowchart | 流程图/架构图 | 2 | 1.1971 | 0.9170 | 1.4773 | 2 |
| strikethrough | 涂改/删除线 | 0 | — | — | — | 0 |

## 样本明细

| id | category | edit_rate | edits | ins | del | sub | gold_chars | pred_chars | gold_proofed | status | latency_s | total_tokens | cost | cached |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 01-requirements-arch | 流程图/架构图 | 1.4773 | 455 | 234 | 0 | 221 | 308 | 542 | 否 | ok | 40.7000 | 3121 | 0 | 否 |
| 02-digitize-pipeline | 流程图/架构图 | 0.9170 | 221 | 39 | 11 | 171 | 241 | 269 | 否 | ok | 19.2500 | 3053 | 0 | 是 |

## 涂改样本（语义化删除）专项

当前评估集 **无真实涂改样本**（留空）。harness 已为该类目预留记录字段 （`deletion_note`），扩充样本后在此专项追踪：明确划掉/涂抹的内容是否不输出（不误删）、模糊划线是否保守保留。
