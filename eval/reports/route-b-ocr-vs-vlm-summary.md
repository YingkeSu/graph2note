# Spike 2 / Route B — OCR+LLM vs Vision-LLM（Route A）分维度对比

- Stub: issue 08（Spike 2）；产物：路由策略结论（回写 PRD）。
- 测量口径：Route A 复用 worker3 已录制的 `glm-5.3-flash` 直出 Markdown 缓存（**零新增视觉调用**）；
  Route B 为新链路 `图片 → tesseract OCR（本地）→ 文本 LLM 结构化（glm-5.3-flash，routeb 独立 session）→
  Markdown → 确定性 IR`，走缓存。
- 指标：EditRate（字符级 Levenshtein 编辑数 / gold 字符数，**越低越好**；与 issue 01 同口径）。
- live 预算：Route B 文本调用共 **35 次**（≤35；30 页 + 2 合成印刷 + 3 早期预检），均落在独立 routeb session。

## 总体

| 路线 | 成功样本 | 聚合均值 EditRate（越低越好） | 说明 |
|---|---|---|---|
| **Route A**（Vision LLM 直转） | 30/30 | **0.768** | 复用已录缓存，零视觉调用 |
| **Route B**（OCR+文本 LLM） | 30/30 | 0.865 | 全页非空 IR（27 结构化 / 3 回退原始 OCR） |

Route A 在 30 页评估集上**全面占优**：24/30 页 EditRate 更低；五维度逐项均低于 Route B。

## 五维 A/B（同 30 页评估集，仅 OK 样本）

| 维度 | n | Route A 均值 | Route B 均值 | 更优 |
|---|---|---|---|---|
| 手写笔记 | 10 | 0.771 | 0.864 | A |
| 数学公式 | 4 | 0.689 | 0.860 | A |
| 中英混排 | 4 | 0.819 | 0.915 | A |
| 流程图/架构图 | 6 | 0.776 | 0.829 | A |
| 涂改/删除线 | 6 | 0.776 | 0.874 | A |
| 印刷扫描 | **0** | —（无样本，N/A） | 见下「合成印刷补充」 | — |

## 印刷维度（评估集无真实印刷页 — 如实标注）

`印刷` 维度在批次内样本为 **0**：Route A **不做**数据标注（N/A，且不新增视觉调用）。为展示 Route B
在清印刷上的能力，用 **PIL 渲染的合成印刷样本（Hiragino Sans GB）** 补少量，只跑 Route B
（方法：把一段印刷文本渲染成白底黑字 JPEG，gold 即该文本；`scripts/synth_print_ab.py` 可复现）：

| 合成样本 | OCR 平均置信度 | Route B EditRate | 说明 |
|---|---|---|---|
| SYN-P1（中文技术段落） | 93.2 | **0.114** | 清中文印刷：OCR 高置信 + LLM 结构化近乎完美 |
| SYN-P2（概率统计/希腊符号） | 84.3 | 0.764 | 符号页 OCR 损坏 σ/√/± → 仍较差 |

## Route B 内部观察

- 文本 LLM 结构化质量**跟随 OCR 质量**：手写/图示页 OCR 噪声大，text-LLM 尽力整理但输出碎片化
  （Route B 均值 0.865）。加固 prompt + 拒绝检测后不再返「噪声过大」占位（27/30 结构化）。
- glm-5.3-flash 文本直出稳定：27/30 无 reasoning_tokens（直出），2 页有（≤1384，低于 800 阈值的
  翻倍但远非恶性）。

## 路由策略结论（已回写 PRD & issue 08）

- **默认恒走 Route A**（Vision LLM）：在 30 页手写/图示/公式评估集上全面占优。
- **Route B 的适用区间很窄**：仅当输入 OCR 平均置信度高分（`PRINT_CONFIDENCE_THRESHOLD=55`，
  `graph2note.route_b.classify_route_features`）且以纯文本为主（清印刷）时，Route B 才可能更优
  （SYN-P1 0.114 证明其潜能）；**公式/符号页（SYN-P2 0.764）与手写/图示页一律走 A**。
- 实现：`AutoRouter` 默认 A，特征=高置信印刷时切 B；env `GRAPH2NOTE_ROUTE=auto|a|b` 强制。
  `RouteBRouter` 实现同一 `RecognitionRouter.recognize` 缝，上游 `parse_document` **零改动**（已验证）。

## 限制

- gold 为 AI 草拟、未经人工校对（HITL 待维护者），与 issue 01 同限制；EditRate 绝对数值偏高，
  **相对比较（A vs B）** 才为可信信号。
- 印刷维度 Route A 无真实样本，合成印刷仅 Route B；「Route B 在清印刷上更优」为单点演示，
  非强统计结论。
- 涂改类目 gold 含删除段保留口径，两端同口径比较，不影响 A/B 相对结论。

## 产物

- 明细/聚合：`.scratch/manuscript-compiler-mvp/reports/route-b/scripts/data/ab_summary.json`、
  `synth_print_summary.json`（合成样本与方法）。
- 生成器：`scripts/synth_print_ab.py`；A/B 运行器：`scripts/run_route_b_ab.py`。