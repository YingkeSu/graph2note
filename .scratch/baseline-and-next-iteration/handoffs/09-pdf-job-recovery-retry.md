# Handoff 09 — PDF 批任务中断恢复与失败页重试

Branch: `ao/graph2note-16/pdf-job-recovery-retry` · Issue: `issues/09-pdf-job-recovery-retry.md` · Status → in-review

## 1. 一句话结论

PDF 批任务的逐页进度已落盘可查；页面刷新或进程重启后任务/页序/成功结果/失败原因仍准确，
进行中但已中断的任务被标记为 `interrupted` 并可恢复；重试只处理失败/未完成页，成功页既不
重复调用模型也不新增内容版本，重试受明确的次数/超时/并发上限约束。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/pdflib.py` | 逐页 `attempts`/`error_kind` checkpoint 写回 `job.json`；`mark_interrupted()` 识别重启中断；`load_jobs()` 启动/按需加载；`committed_document_id()` 幂等提交识别；`retryable_page_indexes()`/`exhausted_page_indexes()`；显式上限 `MAX_PAGE_ATTEMPTS`/`PAGE_TIMEOUT`/`PDF_WORKERS`（存进 job）；`process_pdf` 支持 `pdf_bytes=None` 恢复且只解析未成功页 |
| `graph2note/webapp.py` | `create_app` 启动时 hydrate 持久任务并把 `queued/processing` 归为 `interrupted`；`_get_or_load_pdf_job` 内存→磁盘按需加载；`POST /api/pdf/{id}/retry`；`trigger_pdf` 单飞（single-flight）；重复上传同一 PDF 只续跑未完成页；新增 `pdf_max_page_attempts/pdf_page_timeout/pdf_workers` 参数 |
| `graph2note/webstatic/*` | `interrupted` 状态与尝试次数展示；`#pdf-retry`「重试未完成页」按钮；摘要显示可重试页数 / 达上限提示 |
| `tests/test_pdf_job_recovery.py`（新，9 项） | 离线故障注入：重启恢复、仅重试失败页、提交先于状态落盘、重复上传幂等、并发重试单飞、次数上限、单页超时 |
| `tests/taxonomy.py` | 登记 `test_pdf_job_recovery → ingest`（issue 12 分类自动打标） |

## 3. 关键决策

- **每页状态即检查点**：每次尝试开始（`processing` + `attempts+1`）与结束（success/failed）都
  `save_job`，`save_lock` 串行化写者。刷新/重启后直接读 `job.json`，无需重放。
- **中断判定 = 磁盘状态 + 无活线程**：启动 hydrate 与按需加载时，`queued/processing` 一律归为
  `interrupted`；正在 `processing` 的页回到 `pending`（`error_kind=interrupted`）变为可重试。
  内存中的活任务不受影响（同一进程单实例）。
- **幂等边界 = 确定性文档 id**：页文档 id 恒为 `{pdf_id}-pNNN`。提交前先查库，命中即判 success，
  **不再解析、不再新增版本**——覆盖「落盘成功但状态未落盘」的崩溃窗口；`test_commit_before_status_persist` 验证 0 次额外模型调用、0 个新版本。
- **重试只碰失败/未完成页**：`retryable_page_indexes()` = 状态属于 `pending|failed` 且
  `attempts < 上限`；success/blank/duplicate 为终态。成功页在重试中模型调用数保持 1、版本数不变。
- **有界**：`MAX_PAGE_ATTEMPTS`（默认 2）、`PAGE_TIMEOUT`（默认 300s，单尝试墙钟）、
  `PDF_WORKERS`（默认 2，信号量并发）。达上限后页面 `retryable=false`、`exhausted=true`，
  `/retry` 返回 `triggered=false` 并报告上限，停止自动重试（不无限重试）。
- **单页超时可取消提交**：每页一个 cancel Event；主循环按「该页实际开始时间」计时，超时置位
  并记 `error_kind=timeout`，解析线程在提交前检查 cancel，超时页不落盘、保持可重试。
- **单飞**：`trigger_pdf` 用 `job._running` 原子抢占，运行中再次 `/retry` 返回 `triggered=false`
  （`test_concurrent_retry_is_single_flight`）。
- **落盘/拆分重跑是确定性的**：恢复时重新 `split_pdf`+`cluster_pages`（廉价、顺序稳定），
  `_seed_pages` 保留既有状态，只补种缺失页，成功页不丢。若拆分本身失败，任务记 `failed`。

## 4. AC 逐条证据（离线，`tests/test_pdf_job_recovery.py`）

| AC | 证据 |
|---|---|
| 1 刷新/重启后任务、页序、成功结果、失败原因仍可查；进行中已中断状态可识别并恢复 | `test_page_checkpoints_persist_and_survive_restart`（新 app 实例仍返回 done + 逐页 attempts/status，页序按 index）；`test_interrupted_processing_job_is_detected_on_restart`（crafted processing → `interrupted`，在途页转 pending+`error_kind=interrupted`，`retryable=true`，磁盘同步）；`test_on_demand_load_from_disk_after_memory_clear`（清内存缓存后按需从磁盘加载） |
| 2 只重试失败/未完成页；成功页不重复计费、不新增无意义版本 | `test_retry_only_reprocesses_failed_pages`（retryable=[1]；重试后 p002 success、attempts=2；p001 模型调用恒为 1、`versions` 长度仍为 1）；`test_commit_before_status_persist_recovers_without_reparse`（已落盘页重试时 0 次模型调用、0 新版本） |
| 3 重复上传同一 PDF、并发重试、部分成功后再次运行均保持幂等 | `test_reupload_same_pdf_is_idempotent`（同字节→同 `pdf_id`，续跑后仍 2 份文档无重复，p001 调用数 1、版本数不变）；`test_concurrent_retry_is_single_flight`（运行中重试被拒，不重复解析） |
| 4 明确每页尝试次数/超时/并发；达上限停止并报告 | 常量 + `job.json` 持久化 `max_page_attempts/page_timeout/workers`；`test_max_attempts_stops_and_reports`（cap=2：attempts 到 2 → `retryable=false`、`exhausted=true`，再次 `/retry` `triggered=false` + `exhausted_pages=[1]` + 文案含「上限」；成功页调用数仍 1）；`test_page_timeout_marks_failed_and_job_completes`（`page_timeout=1` + 慢页 → `failed`/`error_kind=timeout`，任务仍 done，超时页可重试） |
| 5 离线故障注入覆盖解析失败、落盘前后中断、重启与重复重试；UI 展示与持久化一致 | 全文件为离线 stub（`RouteARouter` 注入、`pymupdf` 缺失即 SKIP）；覆盖 `fail_first`/`fail_always`/`delay`/`gate` 四类注入 + 手工 crafted 崩溃态；UI 读取的字段（`status/attempts/error_kind/retryable/exhausted/running/max_page_attempts`）均由 `PdfJob.public()` 提供并由 API 测试断言（无浏览器自动化步骤） |

## 5. 如何运行

```bash
scripts/run_tests.sh ingest                 # ingest 模块（含 08+09 PDF 测试）
uv run pytest tests/test_pdf_job_recovery.py # 9 passed
uv run pytest -m "webapp or ingest or meta"  # 91 passed
OPENCODE_API_KEY=dummy uv run pytest         # 全量 464 passed
```

## 6. 未尽事项 / 建议

1. **issue 10 消费**：搜索索引应基于已 `success` 页文档（`{pdf_id}-pNNN`）与 provenance
   (`pdf_id/page_index`)；重解析/删除后需失效对应索引项。
2. **issue 11 消费**：问答引用同样以页文档 provenance 为准；本 issue 的 `committed_document_id`
   与 `job.json` 可作为「来源有效」判定。
3. **provenance 下沉到 version 级**（08 遗留）：当前仍记在 record 顶层；同文档多候选版本时需下沉。
4. **真机长任务**：`PDF_JOB_TIMEOUT`（默认 `JOB_TIMEOUT*20`）是整任务兜底；超大 PDF 可按需调高
   `GRAPH2NOTE_PDF_PAGE_TIMEOUT`/`GRAPH2NOTE_PDF_WORKERS`。
5. **UI 一致性**：本次以 API 断言 + 前端字段消费保证；如需像素级验收，可走 issue 04 的 UI 截图命令。

## 7. 相关文件

- 实现：`graph2note/pdflib.py`、`graph2note/webapp.py`
- 前端：`graph2note/webstatic/{index.html,app.js,style.css}`
- 测试：`tests/test_pdf_job_recovery.py`、`tests/taxonomy.py`
- 上游：`handoffs/08-pdf-upload-parse-library.md`
