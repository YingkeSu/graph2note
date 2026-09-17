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
- 2026-09-17 复审整改（独立审查 `graph2note-136` 裁决 CHANGES_REQUESTED，报告在 `graph2note-136/.scratch/reviews/prr-02-metadata.md`；本分支 `dev/prr-02-metadata`）：
  - **B1/B2 修复**：`metadata._title_lines` 改为以“独立成行的 Abstract 标签”作为首页硬边界，标题按折行连接词（`… for` / `… in` 之类）截断；`_parse_authors` 改为逐行 + 逗号双形态解析，修复 `_AFFIL_RE` 的 `\b` 截断 bug（University/Institute 等此前根本匹配不上）。新增标题**形状门禁** `_title_is_plausible`：超长/含 Abstract/Introduction/多句的“首页大段文本”直接判为未提取（note `title-untrusted`）→ `record.title` 回落文件名，绝不写入 2 KB 首页块。真实 GPT-4/GPT-3 现在解析为 `GPT-4 Technical Report` / `Language Models are Few-Shot Learners`，作者/摘要正确。
  - **B3 修复**：`extract.merge_manual_meta` 只要 `provenance.source == "manual"` 就保留存储值（**含空值**），人工清空 title/authors 不再被重新提取填回；重复提取与重启后一致。
  - **M1**：`enhance.apply_meta_proposal` 增加 `override_fields`；GROBID 可选择覆盖“非 manual 且 confidence 为 low/medium”的自动字段（规则与证据 `grobid:tei` 写在 `webapp._grobid_override_fields`），manual（含清空）永不覆盖。
  - **L1**：批量端点对 `document_ids` 中未知/非论文/失败分别返回 `unknown` / `not-paper` / `failed`，`total` 等于请求条目数。
  - **L2**：真实 fixture 增加显式 `gold`（人工核对标题/作者前缀/摘要开头），新增 `test_real_gold_title_authors_abstract` 按 gold 断言，不再以“非空标题数”当正确率。新增真实来源/哈希可追溯 fixture `gpt3-few-shot`（arXiv 2005.14165，sha256_16 `97fd272f1fdfc186`）与 `gpt4-tech-report`（arXiv 2303.08774，sha256_16 `c33a66dadca2388d`），来源即用户库对应 PDF 内容哈希。
  - **测试**：`tests/test_papers_meta_import.py` 25 例 + 真实 fixture 套件；全量 `pytest -p no:warnings` **1431 passed / 0 failed / 0 error / 0 skipped**。真实库只读复测：17 篇摘要 **17/17**（此前 8/17）、标题 15/17 非空且形状合理（2 篇诚实为空）。**未写入用户库**。
  - **残留（诚实记录）**：`Transformer Circuits Thread AUTHORS` 类页眉仍可能被当标题（形状合理但语义错误，属 issue 03/Z2 的首页印记/页眉抑制）；`doi` 仍可能回退到参考文献（`doi-from-references`，issue 03 领地）；GROBID live 仍未调用。
- 2026-09-17 复审 R2 整改（独立复审报告 `graph2note-136/.scratch/reviews/prr-02-metadata-r2.md`，裁决 CHANGES_REQUESTED）：
  - **R1（高，阻塞）DOI 不得来自参考文献/正文引用**：`metadata._extract_doi(front_text)` 改为逐行扫描**本论文首页元数据区域**——参考/引用行（`et al.`/`[n]`/`Proceedings`/`(年)`/`pp.` 等）直接跳过；带 `doi:`/`doi.org` 标签的行还须像元数据（©/copyright/ISSN/ISBN/arXiv/preprint/received/accepted/published/available at 标记，或该行基本只由 DOI/URL 构成），否则也跳过；截断片段（如 `10.1109/tse`，后缀 <8 或纯字母）拒绝；无证据则 `meta.doi=""` 并记 `doi-not-found`，不再落 `full_text` 回退、不再记 `high` 置信。正例保留：`front_single_column` 的首页 DOI 仍解析为 `10.1109/tkde.2023.1234567`（confidence high）；参考条目自身的 DOI 不受论文级过滤影响（仍在 references 契约内）。
  - **真实 import→persist→view 回归**：`tests/test_papers_meta_import.py::test_real_frozen_text_import_persists_and_views_gold` 现断言 GPT-4/GPT-3 的 `meta.doi == ""` 且 `/view` 一致；真实库只读探针 DOI 由整改前 12/17（多个错配/截断）变为 **0/17**（均为 arXiv 预印本，首页无自身 DOI 证据）。
  - **R2（中）BERT 作者混入机构行**：`_parse_authors` 增加机构/组织裁剪（`_is_affiliation_like` + `_personal_name_tokens`，区分机构行与合法团体作者），并折叠 PDF Unicode 连字（`ﬁ`→`fi`）避免误丢真实作者 `Zac Hatfield-Dodds`；`bert` 现为精确 4 人并写入 gold `author_count: 4`，`Google AI Language` 不再出现。真实库 2/17 无作者（deepseek-v3 / deepseek-r1）如实记录为已知残留。
  - **R3（低）Abstract 独立成段缺口**：`_abstract_block` 支持“标签自成一段、正文在下一段”的跨段收集（并排除作者段落，避免把 byline 当摘要）；回归 `test_abstract_label_own_paragraph_collects_the_next_paragraph`。
  - **year 同源检查**：真实 17 篇只读探针的 year 均来自论文自身 arXiv 印记/版权/页眉（2020–2025），未观察到参考文献年份污染，本轮未改 year 逻辑。
  - **测试**：定向 `test_papers_meta.py` 65 例、`test_papers_meta_import.py` 26 例、真实 fixture 套件全绿；全量见 R2 handoff。
  - **保留**：B1–B3/M1/L1 全部回归保留，未回退。
- 2026-09-17 复审 R3 整改（报告 `graph2note-136/.scratch/reviews/prr-02-metadata-r3.md`，裁决 CHANGES_REQUESTED；口径更正见其 4dcc26c）：
  - **R4a（高，阻塞）删除任意最小长度/必须数字阈值**：DOI 规范（ISO 26324 / DOI Handbook）对后缀无最小长度要求、允许纯字母。`_extract_doi` 不再用 `len(suffix)<8 or no digit`，改为**语法有效性**（`_DOI_RE`）与**本论文来源归属**（`_doi_line_is_metadata`）分离；截断改由**折行上下文**判定：仅当行尾 DOI 断在分隔符后或下一行以 `. - _ /` 开头且拼接后匹配更长时才重建跨行 DOI，避免把完整短 DOI 误并（如 `10.1000/182` + 下一行 `2023` 不得变 `10.1000/1822023`）。正例：DOI Handbook 示例 `10.1000/182`/`10.1000/186` 与纯语法合成 `10.1000/xyz123`/`10.1234/abcdefgh` 均接受（注释明确区分“Handbook 示例”与“未声称注册的合成压测值”）；跨行 `10.48550/arXiv.2405` + `.04434` 重建为 `10.48550/arxiv.2405.04434`。
  - **R4b（中）裸 DOI 仅在整行基本只含 DOI/URL 时接受**：含散文的裸引用（`See 10.1145/… for details.`、`Abstract… See …`）不再成为论文 DOI；显式 `doi:`/`doi.org` 标签仅在带元数据标记（©/copyright/ISSN/ISBN/arXiv/preprint/received/accepted/published/available at）或该行基本只含标签+DOI 时接受；参考文献 `doi:` 标签仍拒绝。新增负例 `test_bare_doi_in_body_prose_is_not_the_paper_doi`。
  - **矩阵回归**（离线，不依赖在线解析）：短/纯字母/长/URL/`doi:`/本论文元数据正例、首页正文裸引用负例、参考 doi: 负例、折行正例与“完整 DOI 行尾不误并”负例。
  - 真实库只读复测 DOI 仍 **0/17**（无误报）；front_single_column 正例仍 `10.1109/tkde.2023.1234567`(high)。保留 R1–R3/B1–B3/M1/L1 行为。
  - 残留不确定性（如实记录）：若 DOI 在字母后断行且下一行以字母续接，无法与下一个词可靠区分，按“无法可靠重建即不接受拼接、保留行内完整候选”处理；这是有意保守，不伪造。
