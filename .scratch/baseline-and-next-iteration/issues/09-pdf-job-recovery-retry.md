# PDF 批任务中断恢复与失败页重试

Status: in-review

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：大批 PDF 处理过程中可恢复，避免重复解析和重复入库。

## What to build

持久化 PDF 批任务的逐页进度，让页面刷新或服务重启后继续看到准确状态，并仅重试失败或未完成页。明确断点和幂等边界，复用已有页级去重与版本机制。

## Acceptance criteria

- [x] 页面刷新和进程重启后任务、页序、成功结果和失败原因仍可查询；进行中但已中断的状态可被识别并恢复。— `test_page_checkpoints_persist_and_survive_restart` / `test_interrupted_processing_job_is_detected_on_restart` / `test_on_demand_load_from_disk_after_memory_clear`
- [x] 重试只处理失败/未完成页；已成功页不重复计费、不增加无意义内容版本或文档。— `test_retry_only_reprocesses_failed_pages`（成功页模型调用恒为 1、版本数不变）/ `test_commit_before_status_persist_recovers_without_reparse`（0 次模型调用、0 新版本）
- [x] 重复上传同一 PDF、同时触发重试和部分成功后的再次运行都保持幂等的任务/页来源映射。— `test_reupload_same_pdf_is_idempotent`（同字节→同 `pdf_id`，2 份文档无重复）/ `test_concurrent_retry_is_single_flight`（运行中重试被拒）
- [x] 明确每页尝试次数、超时和并发限制；达到上限后停止并报告，不能无限重试。— `MAX_PAGE_ATTEMPTS`/`PAGE_TIMEOUT`/`PDF_WORKERS`（写入 job.json）；`test_max_attempts_stops_and_reports`（cap=2 后 `triggered=false` + `exhausted_pages=[1]`）/ `test_page_timeout_marks_failed_and_job_completes`
- [x] 离线故障注入覆盖解析失败、落盘前后中断、重启与重复重试，UI 展示与持久化状态一致。— `tests/test_pdf_job_recovery.py` 9 项均为离线 stub（`RouteARouter` 注入，`pymupdf` 缺失即 SKIP），覆盖 `fail_first`/`fail_always`/`delay`/`gate` + crafted 崩溃态；UI 消费的 `retryable/exhausted/attempts/error_kind/running/max_page_attempts` 字段由 API 断言

## Blocked by

- [08 — pdf-upload-parse-library](08-pdf-upload-parse-library.md)

## Comments

- 2026-09-12 认领：graph2note-16（08 合并入 main 后接力），分支 `ao/graph2note-16/pdf-job-recovery-retry`。
- 2026-09-12 graph2note-16 交付：逐页 checkpoint 落盘 + `interrupted` 识别恢复 + `POST /api/pdf/{id}/retry` 仅重试失败/未完成页 + 幂等提交识别 + 次数/超时/并发上限 + 单飞。新增 9 项离线故障注入测试（`tests/test_pdf_job_recovery.py`）。`-m "webapp or ingest or meta"` 91 passed；全量 `OPENCODE_API_KEY=dummy uv run pytest` 464 passed。详见 `handoffs/09-pdf-job-recovery-retry.md`。
