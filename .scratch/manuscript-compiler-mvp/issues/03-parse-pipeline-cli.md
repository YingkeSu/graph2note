# 解析 tracer：预处理 → Router → VLM → IR → CLI 出 .md

Status: ready-for-agent

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
- [ ] 横拍/旋转图片自动转正后解析；歪斜照片经透视校正，输出明显优于未校正
- [ ] LLM 返回非法 IR 时按策略重试，最终失败给出明确错误而非崩溃
- [ ] 明确划掉的内容不出现在输出；划线模糊的内容保守保留
- [ ] golden-file 测试覆盖路由入口与 IR 校验，CI 无 live 调用

## Blocked by

- 01-spike1-vision-quality-eval（模型选型结论）
- 02-ir-schema-markdown-renderer（IR schema 与渲染器）
