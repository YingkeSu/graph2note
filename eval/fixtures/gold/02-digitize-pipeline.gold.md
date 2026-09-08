# 数字化管线（Digitize Pipeline）

> ⚠️ gold 为 AI 草拟，未经人工校对（HITL 待维护者）。

## 流程

1. 输入：手稿图片 / 扫描件
2. 解析：LLM / OCR 识别（Recognition Router）
3. 中间表示：Document IR
4. 渲染：Markdown / CSS 模板
5. 编译：HTML → PDF

flow: 输入 → 解析(LLM/OCR) → Markdown/CSS 模板 → 编译 PDF
