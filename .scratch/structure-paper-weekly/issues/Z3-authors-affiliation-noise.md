# Z3 — P2 authors 混入机构/URL/邮箱（Y5 补强）

Status: proposed

来源：Y4 真实论文 fixture 发现 #3（`/tmp/spw-Y4-done-report.md` §5；rev-133 verdict §6 复核属实：4/4 篇 authors 混入 affiliation/URL/邮箱碎片；双栏 bert 仍把摘要句并进 authors——Y5 同族但未被 Y5 五轮修复覆盖）。

## What to build

Y5 修复了「摘要并入 authors」的合成回流场景，但真实排版中 `_parse_authors`/`_looks_like_author_line` 仍接收含机构（`Anthropic`、`Google AI Language`）、URL、邮箱、甚至摘要句片段的行。需要作者行净化的下一轮收敛。

## Acceptance criteria

- [ ] Y4 四篇 fixture 的 authors 快照改善（机构/URL/邮箱碎片被过滤或标 degraded 并有 notes）；constitutional-ai 51 人作者不丢真人。
- [ ] bert 双栏摘要片段不再进入 authors（或如实记录为已知失败并解释为何当前不可分）。
- [ ] Y5 31 例 + D1-D4 零回退；CJK/affiliation 既有行为不回退。
- [ ] 全量 pytest 绿；mutation 有牙。

## Blocked by

建议与 Z2 串行（同文件同函数族）。

## 领地

- 独占：`graph2note/papers/metadata.py`、`tests/test_papers_meta*.py`、real fixture 快照。
- 禁止：structure.py（Z1）、references.py（Z5）。

## Comments

- 与 Z2 同领地，派发时须串行或合并为一个 worker。
