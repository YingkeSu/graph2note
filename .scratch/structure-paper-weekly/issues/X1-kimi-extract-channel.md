# X1 — kimi 抽取通道长 prompt 空内容（待裁决）

Status: ready

来源：D 轨 D5a prompt 调优 live 验证；`/tmp/spw-D5a-done-report.md` §风险；`/tmp/review-spw-D5a-verdict.md` §4.1/§4.4/§7；D 轨最终视觉核验 `/tmp/spw-final-vision-report.md` §1/§5-1；BOARD D5a 与 T-vision-final 行。属 D 轨遗留（X 轨）。

## What to build

Diagram 抽取默认通道在「长 prompt + 视觉手稿」下的可用性**裁决与落地**。现状：`GRAPH2NOTE_GATEWAY` 选网关，`resolve_channel("diagram")`（`graph2note/diagram.py:295`、`graph2note/vlm.py:718`）取该网关的 diagram 默认模型；kimi 网关 diagram 默认 `kimi-k2.6`（`eval/gateway.py` 的 `GATEWAYS`）。

证据（D5a 及终检自跑，均为真实 key live 调用）：

- D5a worker live：主通道 **kimi/kimi-k2.6 3/3 失败**——每张手稿 2 次尝试均 `finish_reason=length` 且 `content_len=0`，单次 ~495–505s，**未触发超时**（推理吃满 8000/10000 预算仍无正文）。出处：`/tmp/spw-D5a-done-report.md` §LIVE 验证。
- 同轮回落 **deepseek/deepseek-v4-flash-vision-exp 3/3 ok**（17/8/13s，各 1 次调用）。出处：同上。
- D5a reviewer 未做 kimi 探针（作者已报 kimi ×6 `length`/空内容），自跑 deepseek 6 次抽取中 1 次 01 返回半截 JSON（`length` + `content_len=524` → `parse_fail`）。出处：`/tmp/review-spw-D5a-verdict.md` §4.1/§4.4。
- 终检 `/tmp/spw-final-vision-report.md` §1：kimi 抽取通道 **0 次**调用；deepseek 正式 5 次（01/02/02inc，`validate_diagram_json` 3/3 ok）。

裁决项（需维护者/调度择一或组合）：

- (a) diagram 默认通道切 deepseek 视觉模型（deepseek 网关 diagram 默认经 `DEEPSEEK_MODEL_MAP` 落到 `deepseek-v4-flash-vision-exp`）；
- (b) 提高 kimi 推理/输出预算（`DIAGRAM_MAX_TOKENS`/`DIAGRAM_RETRY_TOKENS` 或请求参数）；
- (c) 换 kimi 视觉模型（`kimi-k3` 等，注意 k3 thinking-only、reasoning 开销更高）；
- (d) prompt 紧凑化（缩减规则/示例长度）。

## Acceptance criteria

- [ ] 裁决结论明确记录在 Comments（选 a/b/c/d 或组合 + 理由 + 决策人/日期）。
- [ ] 按裁决落地最小改动并记录改动面（通道默认在 `eval/gateway.py`/`graph2note/llm_settings.py`，预算在 `graph2note/diagram.py`，prompt 在 `graph2note/diagram.py::SYSTEM_PROMPT`）。
- [ ] live 复现：对 01/02/02inc 三张手稿（或等价样本）在新配置下抽取，**≥3/3** 返回 `validate_diagram_json` ok；逐次记录 HTTP 调用数、耗时、`finish_reason`、`content_len`。
- [ ] 通道切换若影响其他 purpose（`parse_visual`/`ir_text`/`classify`）须验证不回归；无 key 环境全离线测试仍绿。
- [ ] 若预算/时间受限无法 live，须在 Comments 如实记录「未 live 验证」，不得以离线桩替代验收。
- [ ] 全量 `pytest -p no:warnings` 绿。

## Blocked by

无（裁决项；需维护者/调度给出结论后实现）。

## 领地

- 独占：`graph2note/diagram.py`（预算/prompt）、`eval/gateway.py` 的 diagram 通道默认（如需）、`graph2note/llm_settings.py`（如需）、对应测试。
- 联动：`graph2note/diagram.py::SYSTEM_PROMPT` 与 `tests/test_diagram_groups_ir.py` 的 prompt 关键词断言（D5a/R3 曾锁），改 prompt 需同步。
- 禁止：渲染层（`diagrams/matplotlib_renderer.py`、`graphviz_renderer.py`）、`_layout.py`、I 轨文件。

## Comments

- 证据出处：`/tmp/spw-D5a-done-report.md` §风险；`/tmp/review-spw-D5a-verdict.md` §4.1/§4.4、§7-R1/R2；`/tmp/spw-final-vision-report.md` §1/§5-1。
- 与 X2 同源：X2 解决「返回了但被截断」的重试缺口；空内容（`content_len=0`）只能靠本项的通道/预算/prompt 解决。
