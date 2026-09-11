# 上传 PDF 并逐页解析入库

Status: merged

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：PDF 上传、拆页、解析、入库与原页查看。

## What to build

用户通过 Web 上传一个 PDF，看到逐页处理状态，成功页进入文档库并可打开三栏校对界面。保留原 PDF 身份、原始页序与页文档/版本的来源映射，能够回看原 PDF 对应页。首个切片即处理多页 PDF，但不承诺跨进程恢复和局部重试。

## Acceptance criteria

- [x] 小型多页 PDF 从上传到拆页、实际解析和入库全链路可用，不把“待解析”占位当成成功。— `test_pdf_upload_parses_every_page_into_real_documents`（3 页真实文档，markdown 含 golden 内容，断言不含「待解析」）
- [x] 存储稳定的原 PDF 标识和页序，结果排序不受异步完成顺序影响，能从页文档打开原 PDF 对应页。— `test_pdf_stable_identity_and_ordering`（同字节→同 `pdf_id`；pages 按 `page_index` 升序；`/source-page` 返回 PNG）
- [x] 原 PDF 的每个输入页都有可解释状态；空白、重复、成功和失败页可区分，去重后仍保留全部来源映射。— `test_pdf_blank_duplicate_failed_are_distinguishable`（counts `{success:1,failed:1,blank:1,duplicate:1}`，重复页 `merged_into` + 代表页遗留映射）
- [x] 文件类型、大小与页数限制明确；加密、损坏、超限 PDF 有可操作错误；其中一页失败不丢弃成功页。— `test_pdf_rejects_wrong_type/empty/too_large/corrupt/encrypted/too_many_pages` + `test_pdf_partial_failure_keeps_success_pages`
- [x] 离线多页 fixture 通过 Web/API/存储/原页查看验证，解析 stub 与真实模型调用隔离；PDF 来源映射重载后仍成立。— `test_pdf_source_mapping_survives_reload`（FileDocumentStore 落盘 job.json，新建 app 实例后 provenance/`/source-page` 仍成立；解析走可注入 `router_factory`，CI 不触网）

## Blocked by

- [03 — clean-baseline-release](03-clean-baseline-release.md)

## Comments

- 2026-09-11 graph2note-12 交付（Status → in-review）：`pdflib.py` 打通「上传 PDF → 拆页 → 逐页真实解析 → 入库 → 回看原页」，`store.save_document` 增补 `source_pdf/pdf_id/page_index/page_number` provenance，webapp 增加 PDF 上传/状态/原页/页文档接口，前端增加 PDF 上传入口与逐页状态列表；12 项离线测试（`tests/test_pdf_upload.py`）。
- 2026-09-12 graph2note-16 复核并 cherry-pick 到新 main（原提交 49915f4）：冲突文件（`store.py`/`webapp.py`/`webstatic/*`）三方功能共存确认；`-m webapp` 43 passed、`-m ingest` 36 passed、`test_pdf_upload.py` 12 passed、`-m "meta or store or notes or workspace"` 85 passed。合并入 main（847334f）。
- 非阻塞项（归 issue 09）：跨进程恢复与失败页局部重试；跨上传幂等；provenance 下沉到 version 级。详见 `handoffs/08-pdf-upload-parse-library.md`。
