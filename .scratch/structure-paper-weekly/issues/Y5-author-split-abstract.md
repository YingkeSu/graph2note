# Y5 — P2 作者切分把摘要并入 authors（合成 PDF 回流文本）

Status: ready

来源：`/tmp/review-spw-P3-r2-verdict.md` §8；`/tmp/review-spw-P3-r2-verdict.md` §1 live 集成（合成 born-digital PDF 回流文本）。属 I 轨遗留（Y 轨）。

## What to build

`graph2note/papers/metadata.py` 的 `_title_lines` 在「作者行 + 摘要首行落在同一段落块」时会把摘要行并进 `author_lines`，`_parse_authors` 再按逗号切分，摘要文字可能被当作作者写入 `authors`。触发场景是**合成 PDF 的文本层回流**（P3-r2 live 集成用合成 PDF；真实扫描版 VLM 回流同理）：段落合并后 `Abstract—…` 与作者名同块，`_looks_like_author_line` 对「含逗号、≥2 个首字母大写 token」的摘要句返回 True。

要求：作者切分对「摘要起始行」设边界——`_title_lines`/`_parse_authors` 遇到 `Abstract`/`摘要`（`_ABSTRACT_RE`）或句子式长文本时截断 `author_lines`；摘要仍由 `_extract_abstract` 正确提取，不因切分调整而丢失。

## Acceptance criteria

- [ ] 复现：用 P3-r2 的合成 PDF 回流文本（或等价最小 fixture：作者行与 `Abstract—…` 同段）构造失败用例，断言当前 `authors` 含摘要片段，写进 Comments。
- [ ] 修复后：同 fixture 的 `authors` 只含真实作者；`abstract` 非空且以摘要正文开头；`title` 不受影响。
- [ ] 边界不回归：正常单栏/双栏/arXiv 三 fixture（P2 既有）字段逐项不变；CJK 作者列表（顿号/逗号）不变。
- [ ] 作者行与摘要不在同段时行为不变；带 affiliation 碎片的作者行仍按既有规则丢弃。
- [ ] mutation 有牙：去掉摘要边界判断时新断言变红。
- [ ] 离线确定性；全量 `pytest -p no:warnings` 绿。

## Blocked by

无。与 Y4 互补（Y4 提供真实样本，Y5 修此具体缺陷）；可先在 Y4 前用最小合成 fixture 落地。

## 领地

- 独占：`graph2note/papers/metadata.py`（`_title_lines`/`_parse_authors`/相关常量）、`tests/test_papers_meta.py`。
- 禁止：`references.py`、`citegraph.py`、webapp 路由、P1 `textlayer.py`/`structure.py`。

## Comments

- P3-r2 §8 原文：「合成 PDF 回流文本的 P2 作者切分把摘要并入 authors 属 P2 问题，非 P3。」
- 相关常量：`_ABSTRACT_RE`（`^(?:abstract|摘要)\b`）当前只在 `_extract_abstract` 使用；`_looks_like_author_line` 已排除 `_AFFIL_RE` 与含 `@` 行、长度 >260 行，但未排除摘要起始行。
