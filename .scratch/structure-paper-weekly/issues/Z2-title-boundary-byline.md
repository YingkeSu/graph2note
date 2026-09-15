# Z2 — P2 标题边界：标题吞并 byline/摘要

Status: proposed

来源：Y4 真实论文 fixture 发现 #2（`/tmp/spw-Y4-done-report.md` §5；rev-133 verdict §4/§6 复核属实：scaling-laws、bert 的 `title` 吞并作者行甚至摘要开头，已标 degraded）。

## What to build

首页标题/作者/摘要同块回流时，`papers/metadata.py` 的标题提取把 byline（scaling-laws 尾部 `Jared Kaplan ∗`）甚至摘要首段（bert）吞进 `title`。需要收敛标题边界判定。

## Acceptance criteria

- [ ] Y4 fixture 中 scaling-laws/bert 的 title 不再吞 byline/摘要；`expected.json` 对应字段从 degraded 转 ok（或明确的新已知失败）。
- [ ] Y5 全部 31 例与 D1-D4 场景零回退（共用 `_title_lines`/`_looks_like_author_line` 区域，冲突面大，须全量六版对照式自证）。
- [ ] 全量 pytest 绿；mutation 有牙。

## Blocked by

建议与 Z3 串行（同文件同函数族）。

## 领地

- 独占：`graph2note/papers/metadata.py`、`tests/test_papers_meta*.py`、real fixture 快照。
- 禁止：structure.py（Z1）、references.py（Z5）。

## Comments

- 与 Z3 同领地，派发时须串行或合并为一个 worker。
