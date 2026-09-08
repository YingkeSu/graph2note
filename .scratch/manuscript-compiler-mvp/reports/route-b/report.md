# Spike 2 / Route B — OCR+LLM vs Vision-LLM 分维度对比（issue 08）

状态：in-review ｜ 分支：`dev/08-spike2-route-b` ｜ live 文本调用 35 次（≤35）｜ 离线套件 279 通过 / 2 skip

## 结论（路由策略）

- **默认恒走 Route A**：30 页手写/图示/公式评估集上全面占优。
- **Route B 窄适用**：仅清印刷且纯文本为主（OCR 平均置信度 ≥ `PRINT_CONFIDENCE_THRESHOLD=55`）时切换；
  公式/符号页与手写/图示一律 A。
- 实现 `AutoRouter` 默认 A，特征=高置信印刷切 B，env `GRAPH2NOTE_ROUTE=auto|a|b` 强制；
  `RouteBRouter` 实现同一 `RecognitionRouter.recognize` 缝，上游 `parse_document` 零改动（已验证）。

## 数据

| 维度 | n | Route A | Route B | 更优 |
|---|---|---|---|---|
| 手写笔记 | 10 | 0.771 | 0.864 | A |
| 数学公式 | 4 | 0.689 | 0.860 | A |
| 中英混排 | 4 | 0.819 | 0.915 | A |
| 流程图/架构图 | 6 | 0.776 | 0.829 | A |
| 涂改/删除线 | 6 | 0.776 | 0.874 | A |
| 印刷扫描 | 0 | N/A | (合成 SYN-P1 0.114 / SYN-P2 0.764) | B（仅清纯文本） |
| **TOTAL** | 30 | **0.768** | **0.865** | **A（24/30 页更优）** |

EditRate=编辑数/字符数，越低越好。明细见 `scripts/data/ab_summary.json`，印刷合成见 `scripts/data/synth_print_summary.json`。

## 代码要点

- `eval/gateway.py`：新增第 4 个 purpose `routeb`（默认 `graph2note-routeb-01`，env `GRAPH2NOTE_SESSION_ROUTEB`）；
  `transcribe_text()` 文本专用传输 + `ROUTE_B_SYSTEM`/`ROUTE_B_USER_TEMPLATE`/`ROUTE_B_TEXT_MODEL="glm-5.3-flash"`
  （issue 12 经验：不用 deepseek 文本模型，文本端走 Markdown 中间表示再确定性转 IR）。
- `graph2note/ocr.py`：tesseract 封装（`ocr_image`/`ocr_mean_confidence`/`ocr_available`），**绝不抛异常**，失败降级。
- `graph2note/route_b.py`：`route_b_chain`（OCR→文本LLM Markdown→`_markdown_to_ir`→schema 校验，retry≥1，空/拒绝回退原始 OCR）；
  `RouteBRouter`；`classify_route_features`（置信度→印刷概率）；`AutoRouter`；拒绝占位检测 `_looks_like_refusal`。
  加固 prompt 后 27/30 结构化、3/30 回退，无「噪声过大」空拒绝。
- OCR 引擎 tesseract 5.5.2 本机已装（chi_sim/eng，163 语言），经 subprocess 驱动；Python OCR 库未装，
  slides未选型。

## 失败路径安全

- OCR 失败/空 → 空 IR + warning；文本 LLM 空/拒绝 → 回退原始 OCR 文本；全程不崩溃（离线测试覆盖）。
- A/B 运行器与合成生成器均在缓存保护下，重跑零额外 live 调用。

## 风险 / 后续

- gold 为 AI 草拟未人工校对；EditRate 绝对值偏高，只采相对比较。
- 印刷维只有合成样本、Route A 无数据；「Route B 清印刷更优」为单点演示非强统计。
- Formula OCR / Hybrid 路由留作后续切片（本次已验证纯 OCR 对公式页劣于 A，Hybrid 有理由）。
- 需维护者人工校对 gold 后可重算绝对指标。

## 证据文件

- `scripts/data/ab_summary.json`：30 页逐条 A/B EditRate、mode、reasoning。
- `scripts/data/synth_print_summary.json`：合成印刷样本方法 + Route B 指标（图片已 gitignore）。
- 对比主报告：`eval/reports/route-b-ocr-vs-vlm-summary.md`。