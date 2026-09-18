# 论文识别、预览与 AI 阅读 issues

发布日期：2026-09-15。按仓库规范发布于本地 Markdown tracker。

状态更新（2026-09-18）：02 元数据导入已合入 main（merge `03e01b2`，代码 `a104050`）；01 论文预览代码 APPROVE、AC3（macOS 打包应用手工验收）仍 BLOCKED，未合入；其余未开始/未合并。

[诊断证据与方案比较](DIAGNOSIS.md)

| Issue | 优先级 | 依赖 | 状态 |
|---|---|---|---|
| [01 恢复论文封面与原文预览](issues/01-paper-preview.md) | P1 | None — 可立即开始 | in-review（AC3 BLOCKED，未合入） |
| [02 接通论文导入的元数据与参考文献提取](issues/02-metadata-import.md) | P1 | None — 可立即开始 | **merged**（2026-09-18，`03e01b2`） |
| [03 修复真实论文章节误切与阅读顺序](issues/03-layout-parsing.md) | P1 | None — 可立即开始 |
| [04 扩展文本与图片格式的导入预览](issues/04-text-image-preview.md) | P2 | None — 可立即开始 |
| [05 增加 Office 与 EPUB 阅读预览](issues/05-office-epub-preview.md) | P2 | 01-paper-preview |
| [06 让论文检索结果定位到真实页码与段落](issues/06-paper-evidence.md) | P1 | 03-layout-parsing |
| [07 提供带原文证据的一键论文总结](issues/07-one-click-summary.md) | P2 | 06-paper-evidence |
| [08 在论文阅读页接入可追溯的多轮 AI 问答](issues/08-paper-qa-loop.md) | P2 | 06-paper-evidence |
| [09 为论文总结与问答建立可回放的评测 harness](issues/09-ai-harness.md) | P2 | 07-one-click-summary, 08-paper-qa-loop |

建议先处理 01/02/03，再接通 06→07/08→09；04 可独立推进，05 复用 01 阅读器。这里仅表示依赖，不启动 worker 或实现。

既有 issue 不关闭不改写：Y1（PATCH 清字段）、Y2（双存储）、Y4（真实样本）、Y5（元数据误识别）、X5（离线 Markdown 依赖）仍保留。
