# Renderer tracer：Document IR schema + 确定性 Markdown 渲染器

Status: merged

## Parent

[PRD](../PRD.md) Implementation Decisions（Document IR 中心契约、渲染纯函数）；[SPEC](../SPEC.md) FR-005~008、FR-020 前半。

## What to build

建立系统的中心数据契约与其纯函数渲染器，测试先行，不依赖任何 LLM。端到端行为：`Document IR（JSON）→ 校验 → Markdown 字符串（+ 附件落盘接口）`，以 CLI 或库入口形式可演示：给定 IR fixture 输出逐字节可复现的 `.md`。

- Document IR schema：`document_type` + 有序 block 序列；block 类型全集 `heading / paragraph / list / formula / table / code / quote / image / diagram / flow`；diagram/flow 以结构化语义（nodes/edges）表达。
- 校验失败即拒绝，绝不让非法 IR 进入渲染。
- Markdown 渲染规则：heading→ATX、list→Markdown 列表、formula→`$…$` / `$$…$$`、正文特殊字符转义、diagram/flow 走附件接口（本切片只留接口与图片引用语法，绘图实现在 issue 05）。

## Acceptance criteria

- [x] IR schema 有机器可校验的定义，非法 IR（未知类型、缺字段、非法 JSON）被明确拒绝
- [x] 渲染为纯确定性函数：同一 IR 两次渲染逐字节一致（回归测试覆盖）
- [x] golden 测试覆盖全部 10 种 block 类型与边界：空文档、嵌套列表、特殊字符（`*` `#` `_` 反引号）、行内/独立公式、中文全角字符原样保留
- [x] 不触网、不 mock、可直接在 CI 运行
- [x] 有一个最小演示入口：IR JSON 文件进、`.md` 出

## Blocked by

None - can start immediately（与 issue 01 并行）
