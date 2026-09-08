# Spike 1 — 视觉模型直转质量全量评估（正式版）

- 评估集：30 页手稿扫描派生图（来自维护者提供的 4 个多页 PDF，页面裁剪，非打印类）
- 类目覆盖：手写 10 / 流程图 6 / 涂改 6 / 中英混排 4 / 公式 4；**印刷类目缺失**（批次内无真实打印页，仅空白格纸被 AI 误标 print，已剔除）
- gold：AI 草拟（glm-5.3-flash 逐字忠实 prompt）**未经人工校对**（HITL 待维护者）；类目为 AI 判定待人工复核
- 测量标准：生产配置（直出 prompt + 单会话固定 + 首调 max_tokens≈3500 + 1024 降采样 + 120s 硬超时）
- 逐样本明细/逐次调用 meta 见 `detail-<model>.json`

## 双模型对比

| 指标 | glm-5.3-flash | deepseek-v4-flash-vision-exp |
|---|---|---|
| 成功样本 | **30/30 (100%)** | 23/30 (77%) |
| 失败 | 0 | 7× timeout@120s（D27 C52 C50 B11 C05 C41 D07） |
| 样本均值 EditRate（OK 样本，越低越好） | **0.7685** | 0.8400 |
| 聚合 EditRate（Σ编辑/Σgold） | 0.7471 | 0.8452 |
| 延迟均值/最小/最大 (s) | **40.21 / 5.48 / 113.95** | 79.96 / 11.65 / 120.98 |
| reasoning_tokens（OK 样本均值） | 未上报（直出模式） | 4648（思考型） |
| finish_reason 分布 | 全部 stop | stop 21 / length 2 / (超时) 7 |
| 输出截断/过早停 | 无 | 明显（多数 pred 远短于 gold，length 截断 2 例） |

> ⚠️ **限制**：gold 由 glm 草拟 → glm 的 EditRate 偏低有偏；且 EditRate 按字符层面计算，把 Markdown/LaTeX 标记、空行与简报差异都计入，绝对数值偏高（两模型均未达标 <5%）。**相对比较**（glm 更低、无截断、100% 成功）与延迟/可靠性是当下可信信号；最终选型须等人工 gold 校对后再定。

## 分类目 EditRate（仅 OK 样本）

| 类目 | 样本 | glm | deepseek |
|---|---|---|---|
| 手写笔记 | 10 | 0.7708 (10) | 0.8582 (9, D27 timeout) |
| 数学公式 | 4 | 0.6893 (4) | 0.7642 (4) |
| 中英混排 | 4 | 0.8193 (4) | 0.8032 (3, C52 timeout) |
| 流程图/架构图 | 6 | 0.7760 (6) | 0.8989 (5, C50 timeout) |
| 涂改/删除线 | 6 | 0.7759 (6) | 0.8180 (2, B11 C05 C41 D07 timeout) |
| 印刷扫描 | 0 | —（批次无真实打印页） | — |

glm 在除「中英混排」外的各类目一致更低；中英混排基本持平。deepseek 在「流程图/涂改」等高信息密度页尤其容易 120s 超时。

## 数据质量检查（并发窗口污染排查）

因 spike-01 共享 session 与 worker4/5 live 调用同窗口并发，跑批后对 `eval/cache` 全量扫描短补全（<100 字符且对应页有 gold）：
- 命中 **1 例**：`deepseek B11`（pred=18 字符 vs gold=1554）。
- 处理：删除该缓存并**错峰重跑**；B11 重跑仍 120s 超时（无干净快速转写），记为 deepseek 失败样本。
- deepseek 其余短 pred（如 A15 153、B10 171、A02 272）为**真实输出截断**（length 截断/过早停 + 高 reasoning），非缓存污染，予以保留。

## 涂改（语义化删除）行为记录

- gold 采用「保留删除内容 + `<<划掉>>/<<涂改>>` 标记」（逐字忠实口径），而评估 prompt 按语义化删除（明确划掉的不输出、模糊的保守保留）。
- 因此涂改类目两模型 EditRate 均偏高：pred 已删删除段，gold 仍保留删除文 → 删除计数差被计为编辑。这是**已知测量口径差异**，不代表 OCR 失败。
- glm 涂改 6/6 成功且判据稳定；deepseek 仅 2/6 成功（余 4 超时）。

## 初步选型结论（样本受限，非最终）

- **倾向 glm-5.3-flash**：EditRate 更低、无输出截断、100% 成功、延迟均值约减半（40s vs 80s）、无思考型高 reasoning 开销。
- deepseek-v4-flash-vision-exp 在当前生产配置（120s 硬超时）下 23% 样本失败、输出截断明显、延迟近翻倍 —— 直转场景不占优势。
- 该结论基于 30 页 AI 判定/AI 草拟 gold，样本量与 gold 未经人工校对均构成限制；**待人工 gold 校对后复核**方可作为最终选型。

## 产物

- 逐样本报告：`report-glm-5.3-flash.md`、`report-deepseek-v4-flash-vision-exp.md`
- 逐次调用明细（含 attempts/prep/使用量/成本）：`detail-glm-5.3-flash.json`、`detail-deepseek-v4-flash-vision-exp.json`
- 评估集：`eval/fixtures/metadata.json`（含 4 源 PDF 字母→文件名映射、页级类别/gold/来源页码，供 issue 09）