# Z1 — P1 真实排版噪声标题抑制

Status: proposed

来源：Y4 真实论文 fixture 发现 #1（`/tmp/spw-Y4-done-report.md` §5；rev-133 verdict `/tmp/review-spw-Y4-verdict.md` §6 复核属实）。

## What to build

`papers/structure.py` 的标题检测把图/表/坐标轴文字（`Layers`、`+ 16`、`1010`、`1024`、`91.2` 等）当成 section 标题，16–34 页真实论文产生 42–76 个 section（如 `"12 1024"`、`"0 + 16"` 这类坐标轴行）。需要在不误杀真实标题的前提下抑制数值/图表碎片标题。

## Acceptance criteria

- [ ] Y4 四篇真实 fixture 的 section 数显著下降且预期 section（Abstract/Introduction/…/References）不丢失；`expected.json` 快照同步并注明口径变化。
- [ ] 真实短标题（如 `Results`、`Appendix`）不被误杀；合成 fixture 不回退。
- [ ] 抑制规则可解释（provenance/notes 记录被抑制的行），不静默丢弃。
- [ ] 全量 pytest 绿；mutation 有牙。

## Blocked by

无（Y4 已合并，fixture 可复用）。

## 领地

- 独占：`graph2note/papers/structure.py`、相关测试与 `tests/fixtures/papers/real/**/expected.json` 快照。
- 禁止：metadata.py / references.py（Z2-Z4 领地）、渲染层。

## Comments

- 评审提示：抑制阈值的 adversarial 边界（纯数字小节标题、公式编号行）须有测试。
