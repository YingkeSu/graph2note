# PDF 批任务中断恢复与失败页重试

Status: ready-for-agent

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：大批 PDF 处理过程中可恢复，避免重复解析和重复入库。

## What to build

持久化 PDF 批任务的逐页进度，让页面刷新或服务重启后继续看到准确状态，并仅重试失败或未完成页。明确断点和幂等边界，复用已有页级去重与版本机制。

## Acceptance criteria

- [ ] 页面刷新和进程重启后任务、页序、成功结果和失败原因仍可查询；进行中但已中断的状态可被识别并恢复。
- [ ] 重试只处理失败/未完成页；已成功页不重复计费、不增加无意义内容版本或文档。
- [ ] 重复上传同一 PDF、同时触发重试和部分成功后的再次运行都保持幂等的任务/页来源映射。
- [ ] 明确每页尝试次数、超时和并发限制；达到上限后停止并报告，不能无限重试。
- [ ] 离线故障注入覆盖解析失败、落盘前后中断、重启与重复重试，UI 展示与持久化状态一致。

## Blocked by

- [08 — pdf-upload-parse-library](08-pdf-upload-parse-library.md)

## Comments

- 2026-09-12 认领：graph2note-16（08 合并入 main 后接力），分支 `ao/graph2note-16/pdf-job-recovery-retry`。
