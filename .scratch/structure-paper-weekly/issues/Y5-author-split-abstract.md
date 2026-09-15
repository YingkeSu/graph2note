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
- 风险/残留（R1 披露不完整，仅列 prose→name 方向；完整两方向见下方 R2 风险披露）：`_SENTENCE_HINT_RE`/`_PROSE_LEAD_RE` 是启发式 deny-list，仍可能漏判“把英文散文当姓名”的极端标题；真实 PDF 回流样本待 Y4 覆盖。

### Rework R2（D1 修复，Y5）

- 独立 reviewer（会话 `graph2note-115`）裁决 **REJECT**，见 `/tmp/review-spw-Y5-verdict.md` §2。阻塞缺陷 D1：AC「作者行与摘要不在同段时行为不变」被违背。
- D1 最小反例（不同段、有空行）：`A Paper Title\n\nWei Zhang, Li Chen, Ming Li, and Will Smith.\n\nAbstract\nBody text.` —— base `authors=['Wei Zhang','Li Chen','Ming Li','Will Smith']`；R1 修复后 `authors=[]`（4 个作者全丢）。
  根因：`_author_lines_before_abstract` 对 `author_lines` 无条件跑 `_looks_like_sentence_line`，而 `_SENTENCE_HINT_RE` 用 `re.I` 且含 `will`，于是「末句号 + 含 `Will`/`Can`/`The`」的合法 byline 被整行判为句子丢弃；`_looks_like_author_line` 判 True 的行又被新逻辑否决，模块内自相矛盾。
- R2 修复（3 处，均在领地内）：
  1. 句子启发式只在 `kept` 非空时才 `break` —— 永不因句子判据丢掉开启作者块的第一行（该行已由 `_looks_like_author_line` 判定）。
  2. `_SENTENCE_HINT_RE` 去掉 `re.I`，改为区分大小写的**小写**功能词匹配；散文小写、姓名首字母大写，`Will`/`Can`/`The` 不再碰撞。
  3. `_PROSE_LEAD_RE`（行内标签前的姓名前缀判定）同样改为区分大小写，`Will Smith, Can The Abstract—…` 的姓名前缀不再被当散文而整行丢弃。
- R2 新增回归用例（4）：
  - `test_separate_paragraph_byline_ending_with_a_period_is_preserved`（verdict 指定文本：`authors == ['Wei Zhang','Li Chen','Ming Li','Will Smith']`）
  - `test_vlm_superscript_byline_ending_with_a_period_is_preserved`（`Wei Zhang1, Li Chen2, Ming Li3, and Will Brown1.`）
  - `test_wrapped_byline_line_with_a_capitalized_hint_name_is_preserved`（10 作者折行，第二行含 `Will Smith.`）
  - `test_inline_label_after_a_byline_with_capitalized_hint_names_is_preserved`（`Will Smith, Can The Abstract—…`）
- R2 mutation 证据（备份 → 改 → 跑 → 还原，最终工作树干净）：

  | mutation | 结果 |
  | --- | --- |
  | `_author_lines_before_abstract` 改恒等（去掉摘要边界） | 4 个 R1 用例 FAIL |
  | `_extract_abstract` 退回只看 `para[0]` | 2 个 R1 用例 FAIL |
  | 完全移除句子边界 | `test_sentence_like_reflowed_line_is_not_taken_as_an_author` FAIL |
  | 恢复 `_SENTENCE_HINT_RE` 的 `re.I` | `test_wrapped_byline_line_with_a_capitalized_hint_name_is_preserved` FAIL |
  | 恢复 `re.I` + 去掉 `kept` 守卫（= R1 行为） | 3 个 R2 新用例 FAIL |
  | 恢复 `_PROSE_LEAD_RE` 的 `re.I` | `test_inline_label_after_a_byline_with_capitalized_hint_names_is_preserved` FAIL |

- R2 全量：`pytest -p no:warnings` → **1218 passed, EXIT=0**（R1 1214 + 新增 4；`tests/test_papers_meta.py` 单文件 41 passed）。
- **风险披露（R2 当时记为“补全两方向”；R2 verdict 指出仍遗漏 `_PROSE_LEAD_RE` 改大小写导致的 title→abstract 方向，见下方 R3 风险披露）**：
  - prose→name（误收）：无 `Abstract`/`摘要` 标签且散文与姓名同段的极端情况，仍可能把散文行当作者，或把含冷门提示词的标题尾部误当摘要；靠标签边界 + 小写判据收敛，真实样本待 Y4 校准。
  - name→prose（误丢，R1 遗漏方向，即 D1）：合法 byline 被句子判据整行丢弃导致 `authors=[]`。R2 用「`kept` 非空守卫 + 区分大小写」双保险消除，并以 4 个回归用例锁定，覆盖姓名/提示词碰撞（Will/Can/The）与 VLM 上标 + 句号风格。
  - 残余：`_SENTENCE_HINT_RE` 只认小写功能词，句首大写的纯散文行（如 `We present a novel approach.` 且无其它小写提示词）不再被判为句子；此类行通常不满足 `_looks_like_author_line`，且摘要标签路径已独立覆盖。

### Rework R3（D2 修复，Y5）

- 独立 reviewer（会话 `graph2note-123`）复审裁决 **REJECT**，见 `/tmp/review-spw-Y5-r2-verdict.md` §2。D1 确认已修好；但 R2 引入新回归 **D2**。
- D2 最小反例（作者行与摘要不同段）：`A Study Of Abstract Meaning Representation, which is used, in NLP\n\nWei Zhang, Li Chen\n\nAbstract\nBody text.` —— base/R1 `abstract='Body text.'`，R2 `abstract='Meaning Representation, which is used, in NLP'`（标题尾部顶替真实摘要）。
  根因：R2 把 `_PROSE_LEAD_RE` 改区分大小写后，标题式大写前缀 `A Study Of`/`Deep Learning For`/`Towards` 不再命中散文词，被当作 byline 前缀保留 → `author_keys` 非空 → `_extract_abstract` 接受标题里的 “Abstract” 作为标签。该改动对 D1 修复并非必需，只为过 R2 新用例；原 `test_a_title_containing_the_word_abstract...` 因文本用小写 `of` 而侥幸通过（测试盲区）。
- R3 修复（采用 verdict §2.4 方向 1 + 额外健壮性）：
  1. `_PROSE_LEAD_RE` 恢复 `re.I`；head 仅当 **不像作者行** 时才按散文丢弃：
     `if head and (_looks_like_author_line(head) or not _PROSE_LEAD_RE.search(head))`
     —— `Will Smith, Can The`（作者行）保留；`A Study Of`/`Deep Learning For`/`Towards`（非作者行 + 大写散文词）丢弃。
  2. `_extract_abstract` 改为「先找行首标签，再退回行内标签」两遍：自成一行的 `Abstract`/`摘要` 永远优先，避免标题内的行内 “Abstract” 遮蔽真实摘要（同使 `Neural Networks, Abstract Reasoning…` 这类作者样标题前缀不再误发）。
  保留 R2 的 D1 修复（`kept` 守卫 + `_SENTENCE_HINT_RE` 区分大小写），未改 `_looks_like_author_line`。
- R3 新增回归用例（7）：
  - `test_title_with_a_capitalized_function_word_before_abstract_is_not_the_abstract`（verdict 指定文本）
  - `test_capitalized_title_prefix_does_not_turn_the_title_into_the_abstract`（参数化 `Deep Learning For` / `Towards` / `A Survey Of` 三个变体）
  - `test_authorlike_title_prefix_does_not_shadow_the_real_abstract`（`Neural Networks, Abstract Reasoning…`，锁定两遍优先级）
  - `test_inline_abstract_inside_a_title_is_not_invented_without_a_real_abstract`（无真实摘要时不得从标题造摘要，锁定 head 散文护栏）
  - `test_first_byline_line_is_not_dropped_by_the_sentence_heuristic`（锁定 R2 的 `kept` 守卫，回应 R2 verdict §3-M1 覆盖缺口）
- R3 mutation 证据（备份 → 改 → 跑 → 还原，最终工作树干净）：

  | mutation | 结果 |
  | --- | --- |
  | 去掉 `kept` 守卫 | `test_first_byline_line_is_not_dropped_by_the_sentence_heuristic` FAIL |
  | 恢复 `_SENTENCE_HINT_RE` 的 `re.I` | `test_wrapped_byline_line_with_a_capitalized_hint_name_is_preserved` FAIL |
  | head 护栏改 `if head:` | `test_inline_abstract_inside_a_title_is_not_invented_without_a_real_abstract` FAIL |
  | `_PROSE_LEAD_RE` 去掉 `re.I`（= R2 行为） | 同上 FAIL |
  | 去掉两遍优先级（行内按扫描序返回） | `test_authorlike_title_prefix_does_not_shadow_the_real_abstract` FAIL |
  | `_author_lines_before_abstract` 恒等（去掉摘要边界） | 9 个用例 FAIL（含全部 D2 variant） |
  | `_extract_abstract` 只看 `para[0]` | 3 个用例 FAIL |
  | R2 旧 head 护栏（`re.I` + `not search`） | `test_inline_label_after_a_byline_with_capitalized_hint_names_is_preserved` FAIL |

- R3 全量：`pytest -p no:warnings` → **1225 passed, EXIT=0**（R2 1218 + 新增 7；`tests/test_papers_meta.py` 单文件 48 passed）。
- **风险披露（补上 R2 遗漏的 `_PROSE_LEAD_RE` 方向）**：
  - **title→abstract（误替代，R2 遗漏方向，即 D2）**：`_PROSE_LEAD_RE` 大小写敏感化会让标题式大写前缀被当作者前缀，使标题内 “abstract” 被当作摘要标签、真实摘要被顶替。R3 恢复 `re.I` 并用 `_looks_like_author_line` 优先保护 byline，同时两遍优先级以行首标签胜出；以 7 个用例（含大写前缀标题、无摘要标题、作者样标题前缀）锁定。
  - prose→name（误收，同 R2）：无标签且散文与姓名同段的极端情况仍可能把散文行当作者；真实样本待 Y4 校准。
  - name→prose（误丢，R1 遗漏方向，即 D1）：已由 `kept` 守卫 + `_SENTENCE_HINT_RE` 区分大小写消除，回归用例锁定。
  - 残余：标题前缀本身“像作者行”（如 `Neural Networks,`）且无真实摘要段落时，仍可能把标题尾部当摘要；两遍优先级已覆盖“存在真实摘要”的情形，无真实摘要时由 `_PROSE_LEAD_RE` 兜底；真实 PDF 样本待 Y4。

### Rework R4（D3 修复，Y5）

- 独立 reviewer（会话 `graph2note-128`）三审裁决 **REJECT**，见 `/tmp/review-spw-Y5-r3-verdict.md` §2。D1/D2 均确认已修好；但同一失败类仍存 **D3**：折行标题/副标题的**第二行以 `Abstract`/`摘要：` 开头**时，真实摘要被标题尾部顶替（base 正确、R1/R2/R3 全错，该入口从未被堵上）。
- D3 最小反例：`Graph Neural Networks for\nAbstract Meaning Representation\n\nWei Zhang, Li Chen\n\nAbstract\nBody text.` —— base `abstract='Body text.'`；R1/R2/R3 `abstract='Meaning Representation'`。其它触发：`Code Models for|Abstract Syntax Trees`、`Attention Is Still All You Need:|Abstract Representations in Transformers`、中文 `一种基于图神经网络的|摘要：方法研究`。
  根因：`_extract_abstract` 的“规范标签”判定对每行做 `_ABSTRACT_RE.match`，把标题折行后的 `Abstract …` 行当成摘要标签；`_title_lines` 已算出 `title_block` 但未传给 `_extract_abstract`，无法排除标题行。
- R4 修复（verdict §2.5，与两遍优先级正交）：
  1. `_extract_abstract(paragraphs, author_lines, title_lines=None)` 新增 `title_lines` 参数；内部 `title_keys = {_clean(l) for l in title_lines or [] if _clean(l)}`，整行扫描时 `if _clean(line) in title_keys: continue`。
  2. `parse_paper_meta` 调用处把 `_title_lines` 已返回的 `title_block` 传入（已有信息流）。
  3. 保留 R2/R3 的全部 D1/D2 修复（`kept` 守卫、`_SENTENCE_HINT_RE` 区分大小写、head 护栏 `re.I`、两遍优先级）。
- R4 新增回归用例（5 项）：
  - `test_wrapped_title_line_starting_with_abstract_is_not_the_abstract`（verdict 指定文本）
  - `test_wrapped_title_starting_with_abstract_does_not_shadow_the_abstract`（参数化 `Abstract Syntax Trees` / `Abstract Representations in Transformers` / `Abstract Reasoning`）
  - `test_wrapped_cjk_title_starting_with_the_abstract_label_is_not_the_abstract`（中文 `摘要：方法研究`）
- R4 mutation 证据（备份 → 改 → 跑 → 还原，最终工作树干净）：

  | mutation | 结果 |
  | --- | --- |
  | 去掉 `if _clean(line) in title_keys: continue` | 全部 5 个 D3 用例 FAIL |
  | 调用处不传 `title_block` | 全部 5 个 D3 用例 FAIL |
  | 去掉 `kept` 守卫 | `test_first_byline_line_is_not_dropped_by_the_sentence_heuristic` FAIL |
  | `_SENTENCE_HINT_RE` 恢复 `re.I` | `test_wrapped_byline_line_with_a_capitalized_hint_name_is_preserved` FAIL |
  | head 护栏改 `if head:` / `_PROSE_LEAD_RE` 去掉 `re.I` | `test_inline_abstract_inside_a_title_is_not_invented_without_a_real_abstract` FAIL |
  | 去掉两遍优先级 | `test_authorlike_title_prefix_does_not_shadow_the_real_abstract` FAIL |
  | `_author_lines_before_abstract` 恒等 | 6 个用例 FAIL |

- R4 全量：`pytest -p no:warnings` → **1230 passed, EXIT=0**（R3 1225 + 新增 5；`tests/test_papers_meta.py` 单文件 53 passed）。
- **风险披露（补上 R3 遗漏的 D3 方向）**：
  - **title→abstract（误替代，R3 遗漏方向，即 D3）**：**标题行不像作者行**且**存在真实摘要段落**时，折行标题的 `Abstract` 开头行仍被当标签，真实摘要被顶替（base 正确）。与 R3 已披露的“标题像作者行且无真实摘要”是**不同方向**。R4 用 `title_keys` 排除标题块行，以 5 个用例（含三种英文折行 + 中文 `摘要：`）锁定。
  - **残余（base 也错，非严格回归，均已记录）**：
    - 标题行本身“像作者行”（如 `Neural Networks, Abstract Reasoning, and Compositionality`）且无真实摘要段落时，仍会凭空造摘要（base `abstract=''`）。两遍优先级已覆盖“存在行首真实摘要”的情形；无真实摘要时由 `_PROSE_LEAD_RE` 兜底（`A Study Of` 类）。
    - 同一作者样标题 + 真实摘要**行内粘连**在 byline 后（issue 目标布局）时仍返回标题尾部（base `''`），非严格回归。
    - byline 段内第 2 行以 `Abstract` 开头、全大写 byline（`_NAME_TOKEN_RE` 要求 `[A-Z][a-z]+`）在 base 四版同样出错。真实 PDF 样本待 Y4。

### Rework R5（D4 修复，Y5）

- 独立 reviewer（会话 `graph2note-130`）四审裁决 **REJECT**，见 `/tmp/review-spw-Y5-r4-verdict.md` §2。D1/D2/D3 确认已修好；但同一失败类仍存 **D4**。
- D4 最小反例（作者行与摘要不同段）：`Neural Networks, Deep Learning for\nAbstract Reasoning\n\nWei Zhang, Li Chen\n\nAbstract\nBody text.` —— base `abstract='Body text.'`；R1/R2/R3/R4 `abstract='Reasoning'`。
  根因：`_looks_like_author_line` 把标题行 `Neural Networks, Deep Learning for` 当成作者行（`author_at` 落在标题行），折行后的 `Abstract Reasoning` 行既不在 `title_block` 也不在 `author_lines`，R4 的 `title_keys` 只由 `title_block` 构造 → 漏排 → `_extract_abstract` 把它当 canonical 标签返回标题尾部。即两遍优先级（canonical > inline）不区分“真标签”与“标题行首标签”。
  其它触发：作者样标题行在**第 2 行**（`Graph Neural Networks for|Neural Networks, Deep Learning|Abstract Reasoning`）、首行含逗号（`Graph Neural Networks, A Survey of|Abstract Meaning Representation`、`Representation Learning, Advances in|Abstract Meaning Representation`）、byline 段内第 2 行 `Abstract reasoning is a hard problem.`。
- R5 修复（verdict §2.5 方向 1 + 探针例外）：
  1. `_extract_abstract` 的 canonical 标签改为三级优先：**段首 canonical（`index == 0`）> 段中 canonical（`index > 0`）> inline**。真实摘要通常自成一段（段首），而折行标题行 / byline 第 2 行都在段中，因此后者不再顶替。
  2. `title_keys` 排除保留，但仅排除**段中**的标题行（`index > 0`）：标题恰为单词 `Abstract`/`摘要` 时，其段落首行不再被跳过，真实摘要段落（同样是段首）可胜出 —— 修复 R4 verdict §4 探针指出的 `abstract=''` 退化。
  3. D1/D2/D3/两遍优先级/原目标场景修复全部保留。未改 `_looks_like_author_line`；未碰 `references.py`/`citegraph.py`/webapp/P1。
- R5 新增回归用例（8 项）：
  - `test_wrapped_title_after_an_authorlike_title_line_is_not_the_abstract`（verdict 指定，D4 最小反例）
  - `test_authorlike_title_line_does_not_shadow_a_later_abstract_paragraph`（verdict 指定）
  - `test_authorlike_title_wrap_does_not_shadow_the_abstract`（参数化 `Neural Networks, Deep Learning` 三行 / `Representation Learning, Advances in`）
  - `test_byline_line_starting_with_abstract_does_not_shadow_the_abstract`（byline 段内第 2 行）
  - `test_title_and_abstract_in_one_reflowed_paragraph_still_finds_the_abstract`（同段两标签皆段中，锁定 `title_keys` 段中排除）
  - `test_a_title_that_is_only_the_abstract_label_still_finds_the_abstract`（参数化英文 `Abstract` / 中文 `摘要`，锁定探针例外）
- R5 五版对照（自跑 `git show` 载入 base/R1/R2/R3/R4 + 工作树 R5）：

  | 输入 | base | R1 | R2 | R3 | R4 | R5 |
  | --- | --- | --- | --- | --- | --- | --- |
  | D4 最小反例 | `Body text.` | `Reasoning` | `Reasoning` | `Reasoning` | `Reasoning` | **`Body text.`** ✅ |
  | D4 作者样标题第 2 行 | `Body text.` | 错 | 错 | 错 | 错 | **`Body text.`** ✅ |
  | D4 byline 第 2 行 `Abstract` | `Body text.` | 错 | 错 | 错 | 错 | **`Body text.`** ✅ |
  | 探针 `Abstract` / `摘要` 标题 | `Body text.` | 对 | 对 | 对 | **`''`** | **`Body text.`** ✅ |
  | D3 五变体 | 对 | 错 | 错 | 错 | 对 | **对** ✅ |
  | D2 四变体 | 对 | 对 | 错 | 对 | 对 | **对** ✅ |
  | D1 三变体（authors） | 对 | `[]` | 对 | 对 | 对 | **对** ✅ |
  | 原目标回流 / 行内粘连 | 错 | 对 | 对 | 对 | 对 | **对** ✅ |

- R5 mutation 证据（备份 → 改 → 跑 → 还原，最终工作树干净）：

  | mutation | 结果 |
  | --- | --- |
  | 去掉段首优先层（只保留 mid/inline 候选） | D4 系列 + 探针 + `test_authorlike_title_prefix…` 等 9 项 FAIL |
  | 首个 canonical 即胜（= R4 行为） | D4 的 5 项 FAIL |
  | 去掉 `title_keys` 段中排除 | `test_title_and_abstract_in_one_reflowed_paragraph…` FAIL |
  | 去掉 `index > 0` 探针例外（= R4 探针行为） | `test_a_title_that_is_only_the_abstract_label…` 2 项 FAIL |
  | 去掉 `kept` 守卫 | `test_first_byline_line_is_not_dropped…` FAIL |
  | `_SENTENCE_HINT_RE` 恢复 `re.I` | `test_wrapped_byline_line_with_a_capitalized_hint_name…` FAIL |
  | head 护栏改 `if head:` / `_PROSE_LEAD_RE` 去 `re.I` | `test_inline_abstract_inside_a_title_is_not_invented…` FAIL |
  | inline 按扫描序返回（R3 前） | `test_authorlike_title_prefix_does_not_shadow…` FAIL |
  | `_author_lines_before_abstract` 恒等 | 4 项 FAIL |

- R5 全量：`pytest -p no:warnings` → **1238 passed, EXIT=0**（R4 1230 + 新增 8；`tests/test_papers_meta.py` 单文件 61 passed）。
- **风险披露（补上 D4 方向，并纠正 R3/R4 不准确处）**：
  - **title→abstract（误替代，R4 遗漏方向，即 D4）**：**标题行被 `_looks_like_author_line` 误判进 `author_lines`**（`author_at` 落在标题行）时，折行标题的 canonical 开头行不在 `title_block` 中，真实摘要（自成一段）被顶替（base 正确）。R5 用「段首 canonical > 段中 canonical > inline」区分标题行与真标签，以 8 个用例锁定，含 byline 段内第 2 行变体。
  - **探针退化（R4 新引入，已修）**：标题恰为 `Abstract`/`摘要` 时 R4 返回 `''`；R5 的段首例外修复。
  - **纠正 R3 披露**：R3 §5.5/任务书写「byline 段内第 2 行 `Abstract`、全大写 byline 四版同样出错」——**不准确**。自跑 base 在该 byline 布局下 `abstract='Body text.'`（正确），R1-R4 改错，R5 已修正；仅**全大写 byline**（`_NAME_TOKEN_RE` 要求 `[A-Z][a-z]+`）确实 base 与五版均 `authors=[]`。
  - **纠正 R4 披露**：R4 把「标题像作者行」残余限定为“且无真实摘要段落”——不完整；D4 是**存在**真实摘要却被顶替，方向不同，已单列。
  - **残余（base 也错，非严格回归）**：① 作者样标题 + **无**真实摘要 → R5 仍凭空造摘要（base `''`）；② 标题被空行切成两段（`Graph Neural Networks for\n\nAbstract Meaning Representation`）→ 五版均返回标题尾部（base 也错）；③ 作者样标题 + 真实摘要**行内粘连**在 byline 后 → R5 返回标题尾部（base 也 `''`，非严格回归）；④ 全大写 byline → 五版 `authors=[]`。真实 PDF 样本待 Y4。
