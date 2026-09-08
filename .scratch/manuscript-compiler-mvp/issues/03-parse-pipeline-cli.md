# 解析 tracer：预处理 → Router → VLM → IR → CLI 出 .md

Status: merged

## Parent

[PRD](../PRD.md)（四层管线、Recognition Router、语义化删除）；[SPEC](../SPEC.md) FR-001~004、FR-018。

## What to build

第一条真实端到端链路（CLI 形态，无 UI）。端到端行为：`手稿图片文件 → 预处理 → Recognition Router（恒走 Route A）→ 视觉 LLM → 校验通过的 Document IR → Markdown 渲染 → .md 文件`。

- 预处理独立阶段：方向判定与旋转（EXIF 与内容判定结合，矛盾时以内容为准）、透视校正、边缘裁剪、对比度优化；预处理前后图片均可落盘查看。
- Router 为统一入口接口，MVP 实现恒走 Route A，但上游不得绕过。
- VLM 调用按 issue 01 的选型结论（经 opencode go 网关，参数见 `docs/llm/opencode-go.md`）。
- 解析 prompt 要求：输出 Document IR（过 schema 校验，失败重试/降级并给明确错误）、语义化删除（明确划掉/涂抹的内容不输出，模糊时保守保留）。
- 上游调用测试使用录制的真实 LLM 响应 golden files，CI 不 live 调用。

## Acceptance criteria

- [ ] CLI：`parse <image> -o <out.md>` 一条命令完成全链路，`test-images/` 两张手稿产出结构正确的 Markdown
- [x] 横拍/旋转图片自动转正后解析；歪斜照片经透视校正，输出明显优于未校正
- [x] LLM 返回非法 IR 时按策略重试，最终失败给出明确错误而非崩溃
- [ ] 明确划掉的内容不出现在输出；划线模糊的内容保守保留
- [x] golden-file 测试覆盖路由入口与 IR 校验，CI 无 live 调用

## Blocked by

- 01-spike1-vision-quality-eval（模型选型结论）
- 02-ir-schema-markdown-renderer（IR schema 与渲染器）

## Comments

- 2026-09-08 dispatcher 验收合并：92 passed + 2 skipped 离线；AC「test-images/ 两张手稿产出结构正确 Markdown」暂留未勾——img02 全结构 golden 已过，img01 因 glm session 路由推理变体返回空正文（诊断报告 e0bd5dc 已归因），已录空回复 golden 断言干净降级；**待办：网关修复（dev/gateway-speed-fix）合并后由 Track A 重录 img01 golden 补勾**。删除线语义化删除为 prompt 级实现，真实涂改样本验证随评估集（worker 3）跑批后补充记录。

- 2026-09-08 dispatcher：claimed by graph2note-2（Track A 接力，分支 dev/03-parse-pipeline-cli）。**提前启动决策**：依赖 issue 01 的选型结论以「临时选型 glm-5.3-flash + 模型可配置化」替代——依据 Spike 3 报告（glm 是唯一能在真实大图上抽取结构的模型，deepseek 大图空内容）与 FR-017 可替换性要求；01 正式结论若不同，仅切配置不改契约。维持者要求最大化并行度，特此记录。
- 2026-09-08 graph2note-2：提交实现，Status → in-review。handoff 见 `.scratch/manuscript-compiler-mvp/handoffs/03-parse-pipeline-cli.md`。实时选型待 issue 01 结论；网关速度修复（eval/gateway.py, worker 5）合并后需重录 01 golden（见 handoff §3/§5）。
