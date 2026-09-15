# Y5 — P2 作者切分把摘要并入 authors（合成 PDF 回流文本）

Status: ready-for-review

来源：`/tmp/review-spw-P3-r2-verdict.md` §8；`/tmp/review-spw-P3-r2-verdict.md` §1 live 集成（合成 born-digital PDF 回流文本）。属 I 轨遗留（Y 轨）。

## What to build

`graph2note/papers/metadata.py` 的 `_title_lines` 在「作者行 + 摘要首行落在同一段落块」时会把摘要行并进 `author_lines`，`_parse_authors` 再按逗号切分，摘要文字可能被当作作者写入 `authors`。触发场景是**合成 PDF 的文本层回流**（P3-r2 live 集成用合成 PDF；真实扫描版 VLM 回流同理）：段落合并后 `Abstract—…` 与作者名同块，`_looks_like_author_line` 对「含逗号、≥2 个首字母大写 token」的摘要句返回 True。

要求：作者切分对「摘要起始行」设边界——`_title_lines`/`_parse_authors` 遇到 `Abstract`/`摘要`（`_ABSTRACT_RE`）或句子式长文本时截断 `author_lines`；摘要仍由 `_extract_abstract` 正确提取，不因切分调整而丢失。

## Acceptance criteria

- [x] 复现：用 P3-r2 的合成 PDF 回流文本（或等价最小 fixture：作者行与 `Abstract—…` 同段）构造失败用例，断言当前 `authors` 含摘要片段，写进 Comments。
- [x] 修复后：同 fixture 的 `authors` 只含真实作者；`abstract` 非空且以摘要正文开头；`title` 不受影响。
- [x] 边界不回归：正常单栏/双栏/arXiv 三 fixture（P2 既有）字段逐项不变；CJK 作者列表（顿号/逗号）不变。
- [x] 作者行与摘要不在同段时行为不变；带 affiliation 碎片的作者行仍按既有规则丢弃。
- [x] mutation 有牙：去掉摘要边界判断时新断言变红。
- [x] 离线确定性；全量 `pytest -p no:warnings` 绿。

## Blocked by

无。与 Y4 互补（Y4 提供真实样本，Y5 修此具体缺陷）；可先在 Y4 前用最小合成 fixture 落地。

## 领地

- 独占：`graph2note/papers/metadata.py`（`_title_lines`/`_parse_authors`/相关常量）、`tests/test_papers_meta.py`。
- 禁止：`references.py`、`citegraph.py`、webapp 路由、P1 `textlayer.py`/`structure.py`。

## Comments

- P3-r2 §8 原文：「合成 PDF 回流文本的 P2 作者切分把摘要并入 authors 属 P2 问题，非 P3。」
- 相关常量：`_ABSTRACT_RE`（`^(?:abstract|摘要)\b`）当前只在 `_extract_abstract` 使用；`_looks_like_author_line` 已排除 `_AFFIL_RE` 与含 `@` 行、长度 >260 行，但未排除摘要起始行。

### 交付记录（Y5）

- 分支：`dev/Y5-author-split`，base `b56e3c4`（未 push，待独立 reviewer）。改动文件：`graph2note/papers/metadata.py`、`tests/test_papers_meta.py`（仅此两个）。
- 复现（base 代码）：把 `git show b56e3c4:graph2note/papers/metadata.py` 载入后 `parse_paper_meta` 合成回流 front_text（标题行/作者行/`Abstract`/摘要正文同段、无空行）：
  - `authors = ['Wei Zhang', 'Li Chen', 'Ming Li Abstract Document understanding has attracted attention in recent years. We review graph neural network methods for document understanding']`（摘要被并入作者）
  - `abstract = ''`（摘要同时丢失）
  - 最小 `Abstract—…` 同段变体：`authors = ['Wei Zhang', 'Li Chen Abstract—We present a robust method for feature matching', 'which combines geometric verification with learned descriptors']`。
- 修复：新增 `_ABSTRACT_INLINE_RE` 与 `_author_lines_before_abstract`，`_title_lines`/`_parse_authors` 在摘要起始行（`_ABSTRACT_RE`/行内标签）或 `_looks_like_sentence_line` 判定的句子式长文本处截断 `author_lines`；行内标签只保留标签前的姓名片段，片段含英文散文词（`_PROSE_LEAD_RE`）时整行丢弃，避免把标题里的 “abstract” 误当摘要。`_extract_abstract(paragraphs, author_lines)` 改为逐行扫描标签，行内标签仅当标签前文本恰为已知作者行时接受，摘要正文/证据行照常返回。未改 `_looks_like_author_line` 既有判定，未碰 `references.py`/`citegraph.py`/webapp/P1。
- 验收逐条：
  1. 复现 ✅ 见上。
  2. 修复后 ✅ `test_reflowed_author_block_keeps_the_abstract_out_of_authors`（authors == `['Wei Zhang','Li Chen','Ming Li']`；abstract 以 “Document understanding has attracted” 开头；title == “Graph Neural Networks for Document Understanding: A Comprehensive Survey”）、`test_inline_abstract_label_glued_to_a_byline_is_not_an_author`。
  3. 边界不回归 ✅ P2 单栏/双栏/arXiv 三 fixture 既有断言全绿；新增 `test_cjk_author_list_is_unchanged_by_the_abstract_boundary`（张三、李四、王五，顿号）与逗号变体行为不变。
  4. 不同段不变 ✅ `test_author_and_abstract_in_separate_paragraphs_is_unchanged`；affiliation ✅ `test_affiliation_paragraph_is_still_not_part_of_the_author_list`（既有 `_looks_like_author_line` 规则未动）。
  5. mutation 有牙 ✅ 把 `_author_lines_before_abstract` 改成恒等（去掉摘要边界）→ 4 个新用例 FAIL；把 `_extract_abstract` 退回只看 `para[0]` → 2 个新用例 FAIL（authors/abstract 断言）。
  6. 离线确定性 ✅ 纯正则、无时钟/网络；全量 `pytest -p no:warnings` → **1214 passed, EXIT=0**（基线 1207 + 新增 7）。
- 风险/残留：`_SENTENCE_HINT_RE`/`_PROSE_LEAD_RE` 是启发式 deny-list，仍可能漏判“把英文散文当姓名”的极端标题；真实 PDF 回流样本待 Y4 覆盖。
