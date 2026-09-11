# Handoff 08 — 上传 PDF 并逐页解析入库

Branch: `ao/graph2note-12/root` · Issue: `issues/08-pdf-upload-parse-library.md` · Status → in-review

## 1. 一句话结论

Web 上传 PDF → 拆页 → 逐页**真实解析**（非「待解析」占位）→ 入库 → 回看原 PDF 对应页 的
端到端链路已打通；离线多页 fixture 全链路绿，解析 stub 与真实 VLM 调用隔离。本 issue 只做
首个完整切片，**不承诺跨进程恢复与局部重试**（归 issue 09）。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/pdflib.py`（新） | `validate_pdf`（类型/大小/页数/加密/损坏分类校验）、`stable_pdf_id`（内容哈希稳定 PDF 身份）、`PdfJob`/`PageStatus`（逐页可解释状态，`job.json` 可持久化）、`process_pdf`（split→cluster→并发 parse→commit 编排，router_factory 可注入）、`render_pdf_page`（原 PDF 页渲染） |
| `graph2note/store.py` | `save_document` 增补可选 provenance 字段 `source_pdf/pdf_id/page_index/page_number`，落盘 record.json，重载后仍可回查来源映射 |
| `graph2note/webapp.py` | `POST /api/pdf`、`GET /api/pdf/{id}`、`/api/pdf/{id}/original`、`/api/pdf/{id}/page/{i}`、`GET /api/documents/{id}/source-page`；`JobRunner.trigger_pdf` 带独立 `PDF_JOB_TIMEOUT` |
| `graph2note/webstatic/*` | 上传区新增「上传 PDF」入口 + `#pdf-zone` 逐页状态列表（成功/失败/空白/重复徽标，可点开页文档） |
| `tests/test_pdf_upload.py`（新） | 12 项离线用例（详见 §4） |

## 3. 关键决策与偏离

- **PDF 大小上限单独设 50MB**（`pdflib.MAX_PDF_SIZE`），不复用 FR-015 的 10MB：FR-015 明确
  针对 JPG/JPEG/PNG；参考真实样本 `扫描件0908152342_1_1001.pdf`（21 页）实测 **10.9MB**，
  按 10MB 会直接被拒。页数上限 `MAX_PDF_PAGES=200`。
- **稳定 PDF 身份 = `sha256(content)[:16]`**（`pdf-<hex>`）；页文档 id = `{pdf_id}-p{NNN}`，
  页序与文档 id 均与内容稳定（issue 09 幂等/去重可直接复用）。
- **结果排序恒按 `page_index`**：`PdfJob.public()` 与落盘 `job.json` 都对 pages 按 page_index
  排序；解析虽用 ThreadPoolExecutor 并发，但顺序永不受完成先后影响（AC2）。
- **仅 PDF 内近重复去重，不做跨上传合并**：`cluster_pages(keep="first")` 把同 PDF 内近重复页
  （亮度/重扫）映射到代表页文档，重复页记 `status=duplicate + merged_into`，**不再二次调用
  VLM**；跨 PDF/跨上传幂等合并明确留给 issue 09（复用 store_bridge 的 near_duplicate）。
- **空白页不建文档、不计成功**（`status=blank`），符合「不把待解析占位当成功」与 SPEC 非文档页
  策略；每页失败只记该页 `failed`，成功页照常入库（AC4）。
- **来源映射持久化三处**：文档 `record.json`（`pdf_id/page_index`）、`pdfs/<pdf_id>/job.json`
  （逐页来源映射）、`pdfs/<pdf_id>/original.pdf`（原 PDF 原件）。原页查看走 durable 原件
  渲染，**不依赖内存中的 job**，故重载后仍成立（AC5）。
- **偏离说明**：provenance 存在 record 顶层（最新版语义）；若 issue 09/10 把同文档多候选版本
  来自不同源页，应把 provenance 下沉到 version 级。已在下方未尽事项标注。

## 4. AC 逐条证据（离线，`tests/test_pdf_upload.py`）

| AC | 证据 |
|---|---|
| 1 全链路真实解析入库，无占位成功 | `test_pdf_upload_parses_every_page_into_real_documents`：3 页 PDF → 3 个真实文档，markdown 含 golden 内容「状态空间模型」，断言不含「待解析」 |
| 2 稳定 PDF 标识 + 页序稳定 + 打开原页 | `test_pdf_stable_identity_and_ordering`：同字节→同 pdf_id；pages 恒按 page_index 升序；每页文档 `pdf_id/page_index` 正确，`/source-page` 返回 PNG |
| 3 空白/重复/成功/失败可区分 + 去重保留来源映射 | `test_pdf_blank_duplicate_failed_are_distinguishable`：4 页（内容/空白/近重复/注入失败）→ counts `{success:1,failed:1,blank:1,duplicate:1}`，重复页 `merged_into=0` 且 document_id==代表页 |
| 4 限制明确 + 一页失败不丢成功页 | `test_pdf_rejects_wrong_type/empty/too_large/corrupt/encrypted/too_many_pages`（6 项）+ `test_pdf_partial_failure_keeps_success_pages`（1 成功 1 失败，成功页文档可查） |
| 5 离线多页 fixture + stub 隔离 + 重载后映射成立 | `test_pdf_source_mapping_survives_reload`：FileDocumentStore 落盘 job.json 映射正确；**新建 app 实例**（模拟重载）后 `/api/documents` 2 份、provenance 正确、`/source-page` 仍 200 |

- **真实样本冒烟（离线，无 VLM）**：`扫描件0908152342_1_1001.pdf`（21 页/10.9MB）`validate_pdf`
  通过、`split_pdf` 产出 21 页并识别 4 空白页（index 0/5/6/7）、稳定 id `pdf-bc60783feeb2fa91`。
  逐页解析需真实 VLM，未在 CI 跑（符合 stub 隔离要求）。

## 5. 如何运行测试

```bash
# 全部（本项目 pytest 入口 testpaths 仅 tests/）
python -m pytest tests/test_pdf_upload.py -v          # 12 passed
python -m pytest                                     # 300 passed, 9 failed
```

> 9 个失败为**既有环境问题**（本机无 `.env` → `OPENCODE_API_KEY not found`，集中在
> `test_cli_parse/test_e2e_images/test_issue11_parse/test_pipeline`），与本 issue 无关；
> 我新增的 12 项全部离线通过，PyMuPDF 缺失时 `pytest.importorskip("pymupdf")` 干净 SKIP。

## 6. 未尽事项 / 建议

1. **跨上传幂等与恢复（issue 09 消费）**：重复上传同一 PDF、进程中断恢复、仅重试失败页。
   本 issue 已备好 `pdf_id`（内容哈希）、`job.json`、页文档稳定 id，issue 09 可直接复用。
2. **provenance 下沉到 version 级**：当前 `source_pdf/pdf_id/page_index` 记在 record 顶层；
   一旦同文档承接多候选版本（issue 13 合并路径），需把来源字段随 version 落盘。
3. **页数/大小上限**：`MAX_PDF_PAGES=200`、`MAX_PDF_SIZE=50MB` 为初值；真实扫描批量使用时
   可依反馈调整，并可考虑把「第 N 页之后仍可部分处理」改为显式分卷提示。
4. **真实 VLM 逐页解析质量**：待 issue 01 评估集/真实扫描页接入后复跑成功率（本 issue 只验
   证了链路 + 空白页识别 + 校验/降级路径，未对真实 21 页做 VLM 解析质量评估）。
5. **原页查看目前渲染为 PNG**：若需要「打开原 PDF 并定位到页」的原生体验，前端可改为加载
   `/api/pdf/{id}/original` + PDF.js 定位页码（当前 `/page/{i}` 已满足功能 AC）。

## 7. 相关文件

- 实现：`graph2note/pdflib.py`、`graph2note/webapp.py`、`graph2note/store.py`
- 前端：`graph2note/webstatic/{index.html,app.js,style.css}`
- 测试：`tests/test_pdf_upload.py`
- 复用：`graph2note/ingest/{pdf,cluster,hash,model}.py`（issue 09 拆页/去重）、
  `graph2note/pipeline.py`（issue 03 解析）、`graph2note/store.py`（issue 07 入库）

## suggested skills

- diagnose（若后续真实 VLM 逐页解析出现空 content/超时，定位网关与降级路径）
