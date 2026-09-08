# Handoff: Spike 1 视觉质量评估——harness + 30 页全量评估

> from: Track C worker（dev/01-spike1-full-eval）
> to: 维护者（HITL：gold 人工校对 + 评估集抽检）；issue 03/08 接力 worker；issue 09（PDF 拆页）
> status: harness 已交付；30 页全量评估已跑、初步选型已给；gold 人工校对待维护者

## 一句话

评估 harness（`eval/`）已可用：`python -m eval.cli run --model <model>` 一键对指定模型跑全量评估集
计算 EditRate。已用修复后的生产配置（直出 prompt + 会话固定 + 1024 降采样 + 120s 硬超时）对两模型
（glm-5.3-flash、deepseek-v4-flash-vision-exp）各跑 **30 页全量**评估集（缓存复用），给出正式报告与
**初步选型倾向 glm-5.3-flash**。**gold 仍为 AI 草拟、未经人工校对 → 选型需文人工 gold 校对后复核。**

## 全量评估结果（30 页，六分类目，含成本/耗时）

汇总见 `eval/reports/spike1-full-eval-summary.md`，逐页见 `report-<model>.md` / `detail-<model>.json`。

| 指标 | glm-5.3-flash | deepseek-v4-flash-vision-exp |
|---|---|---|
| 成功 / 总数 | 30 / 30 (100%) | 23 / 30 (77%) |
| 样本均值 EditRate（OK，低=好） | **0.7685** | 0.8400 |
| 失败样本 | — | 7×120s 超时（D27 C52 C50 B11 C05 C41 D07） |
| 延迟均值 / 最大 (s) | **40.2 / 114** | 80.0 / 121 |
| reasoning_tokens（OK 均值） | 未上报（直出） | 4648 |
| 输出截断 | 无 | 多处 length 截断 / 过早停 |

- 分类目均值比对见 summary 报告；glm 除「中英混排」外在所有类目一致更低。
- 调用成本：网关订阅内 `cost=0`，未另计费。
- 结论：初步**倾向 glm-5.3-flash**（更低 EditRate、100% 成功、无截断、延迟约减半）。样本受限 + gold
  未人校，**非最终**。

## harness 用法

见 `eval/README.md`。关键命令：

```bash
python -m eval.cli list                                    # 看评估集
python -m eval.cli run --model glm-5.3-flash               # 全量（缓存复用）
python -m eval.cli run --model deepseek-v4-flash-vision-exp
python -m eval.cli run --model glm-5.3-flash --nocache     # 强制重调
python -m eval.cli run --model <m> --only A15,A17          # 子集
```

产物：`eval/reports/report-<model>.md`（总体/分类目/明细/延迟分布/涂改专项）+
`eval/reports/detail-<model>.json`（gold/pred 全文 + 指标 + 逐次调用 meta：latency/reasoning/finish_reason/cost）。
同图同模型结果缓存于 `eval/cache/`（gitignore）不重复调用。

## 数据集（30 页）

`eval/fixtures/metadata.json` 的 `samples` 含 30 个样本（手写 10 / 流程图 6 / 涂改 6 / 中英混排 4 /
公式 4；**印刷类目缺失**——批次内无真实打印页，仅空白格纸被 AI 误标 print，已剔除）。图片在
`eval/fixtures/data/<id>.jpg`，gold 在 `eval/fixtures/gold/<id>.gold.md` + `<id>.meta.json`。

## 给 issue 09 的输入（PDF 拆页 / 去重 / 缺页预警）

来源：维护者提供的 4 个多页扫描 PDF（`test-images/`，主检出目录含原件，工作区不提交 PDF，`*.pdf` 已
入 gitignore）。本 spike 已做拆页与页级元数据，供 issue 09 复用：

- **拆页方法**：pymupdf `get_pixmap(matrix=2.08)` → JPEG quality≈85；A4（595×842 pt）→ 1240×1753 px、
  单页 ≤500KB；30 页派生图共 ~7.33MB。
- **id 约定**：`<源PDF字母><页码>`（1-索引），如 `A15` = A 文件第 15 页。
- **源 PDF 映射**（4 文件）：
  - `A` = `扫描件0908152342_1_1001.pdf`（21 页）
  - `B` = `扫描件0908152342_2_1001.pdf`（21 页）
  - `C` = `扫描件0908153007_1_1001.pdf`（55 页）
  - `D` = `扫描件0908153009_2_1001.pdf`（57 页）
  - 共 154 页，均为无文字层纯图扫描。
- **页级元数据**（已落 `metadata.json` 每条 sample）：`source_pdf`（字母）、`source_page`（原始页码）、
  `category`、`ai_classification`（单行内容概要）、`gold`、`gold_proofed`、`notes`。
- **注意**：源 PDF 与 `*.pdf` 一律不入库；派生页图入库。此套 `metadata.json` 结构可作为 issue 09 拆页
  产物（或 ingest/`out/*/pages/`）的页级元数据 schema 参考。

## gold 校对流程（给维护者 HITL）

- 对每张图：以**原图为准**（不要以模型输出或 AI 草拟 gold 为准，避免污染形成循环），人工修正标准 Markdown。
- 校对后把 `metadata.json` 里该样本的 `gold_proofed` 置 `true`。
- 建议优先校对旧低质量高的样本，先补齐人工 gold，再据其给出**最终**选型。
- EditRate 分母为 gold 字符数；gold 越准确，EditRate 越有意义。

## 涂改（语义化删除）行为记录

- gold 口径：保留删除段并打 `<<划掉>>/<<涂改>>` 标（逐字忠实）；评估 prompt 口径：明确划掉的不输出、模糊的保守保留。
- 两口径差会把「pred 已删删除段 / gold 仍含删除文」计为编辑，令涂改类目 EditRate 偏高——**已知测量差异，非 OCR 失败**。
- glm 涂改 6/6 成功；deepseek 仅 2/6（余 4 超时）。harness 已预留 `deletion_note` 专项记录字段。

## 给 issue 03 / 08 接力的建议

- **issue 03（解析链路 CLI）**：本 harness 的 `eval/gateway.py` 已落地网关提速修复（R1 会话固定 / R2 直出
  降预算 / R3 降采样 / R4 硬超时），可直接复用为 VLM 调用层；golden-file 测试可基于
  `eval/reports/detail-<model>.json` 的 pred 录成 golden。
- **issue 08（Spike 2 / Route B）**：复用本 harness，在 `eval/fixtures/` 补样本后即可对比；新增
  「OCR→LLM」runner 时保持同 `Sample` 结构与报告格式，便于同集 A/B 对比。

## 数据质量说明

- 跑批窗口与 worker4/5 live 调用并发（spike-01 共享 session 抖动），已对 `eval/cache` 扫描短补全污染：
  命中 1 例（deepseek B11，18 字符），清除并错峰重跑，仍 120s 超时，记为失败样本。deepseek 其余短 pred
  为真实截断而非污染。报告标注了该检查结果。
- 部署环境 Python 3.12+；pytest 套件（`tests/`）完全离线（129 passed / 2 skipped）。
- 未提交任何密钥；密钥仅运行时从环境 / 仓库根 `.env` 读取（`.env` gitignore）。

## 维护者手工抽检材料（gold 复核包）

- 为维护者快速人工校对 gold 准备了两份离线复核产物（数据全来自 fixtures/缓存，未调模型）：
  - **Markdown 包**：`eval/reports/gold-review/index.md`（每页一节：缩略图 + gold 全文 + glm 预测全文 +
    差异要点 + 勾选框），另有 `gold/` 30 份可改副本。
  - **PDF 合集**：`eval/reports/gold-review/gold-review-pack.pdf`（A4 纵向，封面 + 目录 + 30 页每样本
    1–3 页：清晰页图 + gold/glm 全文 + 差异要点一行 + 复核勾选行；中文用 STSong-Light）。
- 建议抽检顺序：涂改类 6 页优先 → 公式 4 页 → 其余；改后把 `gold/<id>.gold.md` 同步回
  `eval/fixtures/gold/` 并置 `gold_proofed=true`。
- 生成命令：`python -m eval.gold_review`（MD） / `python -m eval.gold_review --pdf`（PDF）；
  依赖 reportlab（已入 pyproject dev extras）。