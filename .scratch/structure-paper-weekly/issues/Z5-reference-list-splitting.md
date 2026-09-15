# Z5 — 真实参考文献列表切分

Status: proposed

来源：Y4 真实论文 fixture 发现 #5（`/tmp/spw-Y4-done-report.md` §5；rev-133 verdict §4/§6 复核属实：无编号/字母键列表（`[ACDE12]`、`[Askell et al., 2021]`）被整节并成 3–9 个跨页巨条目，fragments 最高 330；当前行为保守合并 + provenance、覆盖率 100%，不静默造条目）。

## What to build

`papers/references.py` 对编号/字母键混排、无编号真实参考文献列表切分不足。需要在保持「保守合并优先、不造条目」原则下提升切分粒度。

## Acceptance criteria

- [ ] Y4 四篇 fixture 的条目数显著接近真实文献数；每条目仍是原文子串、拼接覆盖率不下降（不丢不造）。
- [ ] 欠切分时仍保守合并 + provenance；不得为追求粒度引入凭空条目。
- [ ] 合成 fixture 与既有 references 测试零回退；全量 pytest 绿；mutation 有牙。

## Blocked by

无（references.py 独立领地）。

## 领地

- 独占：`graph2note/papers/references.py`、`tests/test_papers_references*.py`、real fixture 快照。
- 禁止：metadata.py（Z2/Z3/Z4）、structure.py（Z1）。

## Comments

- 难度高于 Z1-Z4（真实列表格式多样），评审须带真实样本对抗。
