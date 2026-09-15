# Z6 — 摘要标签定位语义化（Y5 残余收敛）

Status: proposed

来源：Y5 五审 verdict `/tmp/review-spw-Y5-r5-verdict.md` F1/F2/残余① + Y4 真实 fixture 发现 #7（bert 双栏摘要丢失，Y5 D3 副作用，消融证实机制）。

## What to build

Y5 五轮修复以「段首 canonical > 段中 canonical > inline + title_keys 段中排除」收敛了合成场景，但定位仍是纯几何判据，残余四类（均 base 也错或真实排版触发）：

1. **F1**：真实摘要在段中、其后另有段首 `Abstract …` 假标签时，段首优先误伤（base 同错，非回归）。
2. **F2**：`index > 0` 探针例外使「标题段首行以 `Abstract …` 开头且存在真实摘要段」退回 base 的标题尾部；verdict 建议把探针例外收窄为「`title_block` 整块恰为标签本身（`_clean(title) in {'abstract','摘要'}`）」。
3. **残余①**：作者样标题 + 无真实摘要时凭空造摘要；verdict 建议把「作者样标题行」判据与摘要标签判据解耦。
4. **Y4 #7（真实触发）**：双栏 bert 标题块吞掉 byline + `Abstract` 行 → 该行被判 title_keys 跳过 → 真实摘要完全丢失（`test_two_column_byline_absorption_drops_the_real_abstract` 已锁定机制，修好后该用例变红提醒校准 fixture）。

## Acceptance criteria

- [ ] F1/F2/残余① 各补回归用例并修复（或论证不修并记录）；bert 双栏摘要恢复（若依赖 Z2 标题边界先行则如实记录依赖）。
- [ ] Y5 31 例 + D1-D4 六变体零回退；Y4 fixture 快照同步。
- [ ] 修复方向须带语义判据（如 `_looks_like_sentence_line` 类）而非继续堆几何特例；全量 pytest 绿；mutation 有牙。

## Blocked by

可能与 Z2（标题吞 byline 是 bert 案例的上游）有依赖——派发时评估是否合并或串行。

## 领地

- 独占：`graph2note/papers/metadata.py`、`tests/test_papers_meta*.py`、real fixture 快照。
- 禁止：structure.py（Z1）、references.py（Z5）。

## Comments

- 与 Z2/Z3 同领地，三项须统一排期（建议一个大 worker 或严格串行）。
