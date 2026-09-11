# 基于 PDF 内容问答并提供页级引用

Status: merged

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：对已导入 PDF 提问并核对答案来源。

## What to build

在已选择的 PDF 检索范围内，用户提出一个问题，系统检索相关内容后调用文本模型回答，展示可回到原页的证据引用。首版采用无长期会话的单轮问答；检索无证据时明确回答证据不足，沿用已配置模型供应商，不要求视觉 QA 开发工具参与产品运行。

## Acceptance criteria

- [x] 从范围选择、提问、检索、模型生成到答案与页级引用展示有完整 Web/API 路径，引用能打开原 PDF 对应页。— `test_answer_with_valid_citations_and_links`（引用 `review_url`/`source_page_url`/`pdf_page_url` 均可用）/ `test_scope_limits_answer_to_one_pdf`
- [x] 引用只能指向本次检索到的有效来源；模型伪造的文档/页码/引用标识被拒绝或标记不可信。— `test_fabricated_citation_is_rejected`（`[99]` → `untrusted_citations`，仅保留 `[1]`）/ `test_validate_citations_unit`
- [x] 无命中、证据不足、请求超时和模型不可用分别有明确状态，不伪造答案或把失败当成空答案。— `test_no_evidence_skips_the_model`（不调模型）/ `test_model_timeout_state` / `test_model_unavailable_state_and_bounded_retries`
- [x] 检索内容作为资料而非指令；输入规模、生成时长、重试次数有边界，记录模型和 token 使用，不泄露凭证。— `test_prompt_injection_is_treated_as_data` + `limits`/`usage`/`model` 断言且响应无 `api_key`
- [x] 更新/删除后的索引与回答来源一致；离线 stub 测试覆盖有答案、无证据、伪造引用和资料中的指令注入，少量 live 验收单独显式运行。— `test_deleted_source_is_not_cited`；`tests/test_pdf_qa.py` 10 项均注入 stub 文本模型，无 live 调用

## Blocked by

- [10 — pdf-content-search](10-pdf-content-search.md)

## Comments

- 2026-09-12 认领：graph2note-16（10 合并入 main 后接力），分支 `ao/graph2note-16/pdf-grounded-qa`。
- 2026-09-12 graph2note-16 交付：`pdfqa` 单轮问答（issue 10 排名 OR 检索 + 注入式文本模型 seam + 引用只接受本次检索集 + 无证据/超时/不可用明确状态 + 有界与 usage 记录），`POST /api/pdf/ask`，检索区提问框与答案/引用渲染。新增 10 项离线测试（`tests/test_pdf_qa.py`）。`-m "webapp or ingest or meta"` 107 passed；全量 480 passed。AO Browser panel 实机确认 UI 元素 + 真实 API 请求返回 `answered/citations=[1,2]`，并抽取 `renderPdfAnswer` 验证渲染输出。详见 `handoffs/11-pdf-grounded-question-answering.md`。
- 2026-09-12 复核通过（无整改项）并合并入 main（a0fd436）。验收：10 项离线 stub 测试、引用校验与失败状态正确、注入按数据处理、删除后来源一致。
- **本轮迭代收官**：baseline-and-next-iteration 全部 11 项 issue（01–11）+ 12（测试分类）均已交付并合并入本地 main（未 push）。
