# Handoff: Spike 1 视觉质量评估——harness 与冒烟交付

> from: Track C worker（dev/01-spike1-harness）
> to: 维护者（HITL：评估集扩充 + gold 人工校对）；issue 03/08 接力 worker
> status: harness 已交付并冒烟通过；选型结论待数据充足后给出初步观察

## 一句话

评估 harness（`eval/`）已可用：`python -m eval.cli run --model <model>` 一键对指定模型
跑全量评估集，计算 EditRate；`test-images/` 两张手稿已对两模型（glm-5.3-flash、
deepseek-v4-flash-vision-exp）完成冒烟，产出真实报告。**当前 gold 为 AI 草拟、未经人工校对，
EditRate 偏高（~92%–148%），不具选型意义，仅验证 harness 链路。** 后续请维护者补齐并人工校对
gold 后，用本 harness 重跑出可用的选型数据。

## harness 用法

见 `eval/README.md`。关键命令：

```bash
python -m eval.cli list                                    # 看评估集
python -m eval.cli run --model glm-5.3-flash               # 全量（缓存复用）
python -m eval.cli run --model deepseek-v4-flash-vision-exp
python -m eval.cli run --model glm-5.3-flash --nocache     # 强制重调
```

产物：`eval/reports/report-<model>.md`（总体/分类目/明细/涂改专项）+
`eval/reports/detail-<model>.json`（gold/pred 全文 + 指标 + 成本/耗时/token）。
同图同模型结果缓存于 `eval/cache/`（gitignore）不重复调用。

## 冒烟结果（2 模型 × 2 图，含成本/耗时）

| 模型 | 样本 | EditRate | status | latency_s | comp_tokens | comment |
|---|---|---|---|---|---|---|
| glm-5.3-flash | 01-requirements-arch | 1.4773 | ok | 40.7 | 246 | 目录/内容均可读，含「思考被截断重试」路径验证 |
| glm-5.3-flash | 02-digitize-pipeline | 0.9170 | ok | 19.3 | 167 | 结构清晰，含少量 OCR 噪声 |
| deepseek-v4-flash-vision-exp | 01-requirements-arch | 1.4740 | ok | 64.5 | 4909 | 内容完整，补充较多细节 |
| deepseek-v4-flash-vision-exp | 02-digitize-pipeline | 0.9295 | ok | 54.1 | 5547 | 全链路文字转录较全 |

- 调用成本：网关订阅内 `cost=0`，未另计费。
- 汇总（未经人工校对 gold 作为分母）：glm 均值 1.1971、deepseek 均值 1.2017，两者近似。
  **不适合作为选型依据**。

## 数据集怎么扩充

见 `eval/fixtures/CATEGORIES.md`。要点：

1. 新图入 `test-images/`（或 `eval/fixtures/data/`），把 id/路径/类目填入 `eval/fixtures/metadata.json` 的 `samples`。
2. 写 `eval/fixtures/gold/<id>.gold.md`；`gold_proofed` 初始 `false`。
3. `python -m eval.cli list` 确认入列 → `python -m eval.cli run --model <model>`。
4. 六类目：handwriting/print/formula/mixed/flowchart/strikethrough。当前仅 flow chart 覆盖，
   其余五类样本待维护者提供；涂改类目样本现为空（harness 已预留 `deletion_note` 记录语义化删除表现）。

## gold 校对流程（给维护者 HITL）

- 对每张图：以**原图为准**（不要以模型输出为准，避免模型输出污染 gold 形成循环），人工书写标准 Markdown。
- 校对后把对应 `metadata.json` 里该样本的 `gold_proofed` 置 `true`。
- 建议优先校对可重复的样本，并以「先补齐评估集规模（≥30 张）、再逐一校对」推进。
- EditRate 分母为 gold 字符数；gold 越准确，EditRate 越有意义。

## 给 issue 03 / 08 接力的建议

- **issue 03（解析链路 CLI）**：本 harness 的 `eval/gateway.py` 可直接复用为 VLM 调用层
  （含思考截断回退逻辑已验证）。golden-file 测试可基于 `eval/reports/detail-<model>.json`
  的 pred 录制成 golden。注意把本 harness 发现的「max_tokens=10000 下 glm 偶发思考过长被截断、
  正文为空」回退策略带进主线调用层（建议在 router/parse 层做同款降级）。
- **issue 08（Spike 2 / Route B）**：复用本 harness，在 `eval/fixtures/` 按五维（手写/印刷/公式/
  中英混排/小字）补样本后即可对比。当前流水线是「图片 → VLM → Markdown 直转」，为 Route B 的
  「OCR → LLM」新增 runner 时保持同样 `Sample` 结构与报告格式，方便同集 A/B 对比。
- **模型选型**：数据不足，未下最终结论。初步观察（n=2/模型，均为 flowchart）两模型 EditRate 近似、
  内容都可读；glm 更快更简、deepseek 更详尽。等评估集补齐 + gold 校对后再定量选型。

## 已留的坑 / 注意事项

- gold 均未人工校对；报告会明确标注「未经人工校对」。
- 部署环境 Python 3.12+；pytest 套件（`tests/`）完全离线，不触网。
- 未提交任何密钥；密钥仅运行时从环境 / 仓库根 `.env` 读取。