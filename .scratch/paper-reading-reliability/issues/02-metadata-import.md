# 02 — 接通论文导入的元数据与参考文献提取

Status: in-review
Priority: P1

## 现状与证据

17/17 view.meta.title 为空；导入 _commit_text_layer 明确写空 PaperMeta 和 references；parse-metadata 是独立的无状态端点。

详见 [实际诊断与调研](../DIAGNOSIS.md)。本 issue 仅发布，尚未实现。

## What to build

导入后执行现有元数据/参考文献提取并持久化，阅读页和库卡片读取一致结果。自动提取失败与文件导入成功分别显示。为历史论文提供显式重新提取入口，保护用户手工修改。先复用现有 P2，再用 GROBID 作为学术标题、作者、参考文献候选解析器；外部补全只作为可选项且必须标注证据。

## Acceptance criteria

- [x] 新导入 GPT-4 与 GPT-3 正确显示论文标题、作者和摘要，而非文件名；年/DOI 无证据时为空并可解释。
- [x] 历史 17 篇支持逐篇或批量补提取；重复执行幂等，失败可重试，保留手工字段。
- [x] 首个 References 区能解析并展示文献项，失败项保留原文和状态，不能伪造 DOI 或库内链接。
- [x] 导入结果、metadata 和 view 返回一致；进程重启后保持一致；覆盖完整 import→persist→view 而非只测 parse-metadata。
- [x] 衔接既有 Y1 部分更新清字段与 Y5 作者摘要混淆；未经修复不能通过这些用例。

## Blocked by

None — 可立即开始

## 参考方案

- [官方资料](https://grobid.readthedocs.io/en/latest/Introduction/)

## Comments

- 2026-09-15：基于运行中应用及官方资料发布；验收指标为未来实现要求。
- 2026-09-16 交付（worker `graph2note-138`，分支 `dev/prr-02-metadata`，基线 main `f771b9d`；本地提交，未 push/未建 PR）：
  - **接线**：`graph2note/papers/extract.py`（新）把现有 P2 `parse_paper_text` 跑在已存全文上并写 P2 槽；`pipeline._commit_text_layer` / `_commit_vlm_fallback` 提交后调用它，并把 `meta_status` / `meta_error` 记入 `PaperJob`（导入 `done` 与提取 `ok|empty|failed` 分开显示）。导入标题优先用抽取标题（无标题时回落文件名），库卡片/搜索/阅读页同源。
  - **保护手工字段**：`provenance.source == "manual"` 且非空的字段在重新提取时保留，其余字段按确定性结果刷新；重复执行同一文本写出的槽位字节一致（notes 去重）。
  - **入口**：`POST /api/papers/{document_id}/metadata/extract`（逐篇，幂等、可重试、失败不破坏旧槽）与 `POST /api/papers/extract-metadata`（批量，逐项隔离失败，可按 `document_ids` 过滤）；前端阅读页工具栏新增「重新提取元数据」按钮并显示结果。
  - **参考文献状态**：`/view` 每条参考文献附 `references_provenance[].notes` 作为 `notes`，前端渲染状态标签；`raw` 始终保留，`doi`/`resolved_document_id` 无证据时为空，绝不伪造。
  - **GROBID（可选）**：`graph2note/papers/grobid.py` 提供纯 TEI→字段映射与可注入 transport；仅 `{"grobid": true}` 且配置 `GRAPH2NOTE_GROBID_URL` 或注入 transport 时才调用，缺失/不可达时降级并记 `grobid-unavailable:*`；只填空字段，证据标 `grobid:tei`。**未做 live GROBID 调用**（环境无服务，仅离线 fixture + 注入 transport）。
  - **测试**：`tests/test_papers_meta_import.py`（18 例，离线）+ 既有套件；`pytest -p no:warnings` 全量 **1386 passed / 0 failed / 0 error / 0 skipped**（基线 1368，+18）；`node tests/paper_view.mjs`、`node tests/upload_pdf_intercept.mjs` 绿。mutation：关掉导入接线 → 8 例红；关掉手工字段保护 → 1 例红；去掉 view `notes` → 1 例红。
  - **真实资料只读验证**：对用户库 17 篇真实论文（未写入）跑确定性解析 → 标题 15/17、摘要 8/17、参考文献 17/17。`rlhf-helpful-harmless`、`deepseek-v2` 标题仍为空（首页/版式启发式限制，属 03/Z2 领地）；部分标题含作者/摘要残尾（同属标题边界问题）。**未批量修改用户库**，需另行授权。
  - **限制**：GROBID live 未验证；`size/位置` 型标题边界缺陷由 issue 03 处理；历史论文的库卡片标题在补提取后经 `_paper_card_fields` 读同一 P2 值，但记录 title 本身不变。
