# Handoff: issue 12 — Route A 产品管线真实扫描页空 IR 修复

Status: in-review 　branch `dev/12-route-a-empty-ir`（自 origin/main）
Primary consumer: coordinator / issue 08 Route B 设计 / worker 4 issue 10 交叉验证对齐。

## 一句话结论

「单阶段 VLM 直接出 IR-JSON」在密集扫描页不稳定（返回合法但空 blocks），已改为
**两阶段**：VLM→Markdown（eval 已验证策略 + 空/推理耗尽时升级 token 预算）→
确定性 markdown-parser→IR（对非空输入永不返回空），集中在 `graph2note/vlm.py`，Router 缝不变。

## 根因（供 08 Route B 设计参考）

1. 产品 IR-JSON 直出 prompt 在板书/大图/密集页常返回 `blocks: []`（completion 很短的“合法空 IR”），
   渲染后空 .md，EditRate 病理性 1.0（issue 03/11 证据）。
2. eval harness 的「Markdown 直转」prompt 对同批页稳定非空（worker3 cache: A02=1786 字符等）。
   差别在**任务形态**（像素→JSON 结构 vs 像素→Markdown 文本），而非仅是措辞。
3. 推理路由下 3500 token 预算可被 reasoning 吃满而 content 空（worker4 issue10 同源）。
4. 本次又定位一个并发诱因：live gateway 在共享会话 `spike-01` 被 worker3 批次并发占用时，
   VLM 返回极短「本页全黑」（session 退化，issue 11 已录同类），属服务层抖动。

## 关键决策

- stage-1 prompt：复用 eval `DEFAULT_SYSTEM`/`DIRECT_USER_TEMPLATE` 措辞族（单一网关策略，issue 11 O1）。
- stage-1 预算升级：内容空或 `finish_reason=length`（推理耗尽）时内部重试一次，
  `max_tokens` 升到 `GRAPH2NOTE_MARKDOWN_RETRY_TOKENS`（默认 10000，对齐 worker4 verify/run_model），
  配合硬超时避免回到 300s runaway（R2/R4 框架内）。
- stage-2 默认确定性 parser `_markdown_to_ir`：保序、合法、**对非空输入永不返回空**；零实时调用、可离线端到端测试。
- 可选 `GRAPH2NOTE_IR_MODE=llm` 文本 LLM 重构：实测 `deepseek-v4-flash` 强推理、花 max_tokens 返回空，
  **不可靠，故默认关闭**；muse 系列一律禁用（responses 端点、用输入训练）。
- prompt/模型/配置集中在 `graph2note/vlm.py`；`call_ir(image, model, session=..., recover=...)` 签名与
  数量不变 → router.py 与 worker4 verify/engine.py 兼容。

## 实测证据（量化）

- img01（architecture）：修复前空 .md；修复后 **539 字符 / 11 blocks**（live，stage-1 升级预算后）。
- 评估集 6 类目页（A02 公式 / A09 删除线 / A10 混排 / A13 流程图 / A15 手写 / img01 架构）：
  **修复前 6/6 空 IR；修复后 6/6 非空 IR**。
- EditRate（service-independent：已落盘已验证转录 → 产品 stage-2 → render → 与 gold）：
  A02=0.768 / A09=1.105 / A10=0.846 / A13=0.809 / A15=0.903 / img01=1.448（非退化；EditRate 绝对质量属 issue 01/11 顺延）。
- 全量离线测试：**157 passed, 2 skipped**。

## 交付物（branch dev/12-route-a-empty-ir）

- `graph2note/vlm.py`：两阶段 + `_markdown_to_ir` + stage-1 预算升级 + 常量与 `__all__`。
- `tests/test_issue12_twostage.py`（9 项）；`tests/test_e2e_images.py`（新增 img01 非空 golden e2e，
  保留空-golden 降级 seam）；`tests/golden/real-img01.golden.json`（11 blocks，替换空 golden 语义）。
- `reports/route-a-empty-ir/report.md` + `scripts/issue12_two_stage.py` + `validated_editrate_offline.py`
  + `scripts/data/summary.json`（live）、`editrate_offline.json`（确定性）。
- issue 12 文件：Status: in-review，AC 1–5 勾选。

## 风险 / 建议

- 修复保证“有内容就非空”，但不保证“渲染时服务层能拿到正文”。并发/共享会话会导致 VLM 短完成；
  建议并发压力测试前协调共享会话路由，复用 eval 已验证转录做确定性验证。
- 若后续要在 IR_MODE=llm 下用文本模型重构 IR：需挑选**非强推理**或**足够输出余量**的文本模型，
  并监控 reasoning_tokens 用尽（当前默认 parser 规避）。
- EditRate 绝对质量提升（二次转录纠错、公式/流程图结构升级）联动 issue 01/11 顺延项；
  08 Route B（OCR 路线）可直接复用 stage-1 已验证转录策略。