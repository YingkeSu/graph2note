# Z7 — X6 评审跟进（文档/测试小项）

Status: proposed

来源：X6 verdict `/tmp/review-spw-X6-verdict.md` Findings F1/F2/F3/F5（均非阻塞）。

## What to build

1. **F2**：`_compact_text` docstring 与报告措辞「从原始 label 重排」不符——label 用 raw_labels，note 用已按 16 units 适配的文本。改为如实描述。
2. **F3**：docstring 明示的两条边界无测试——补合成用例：① >28 列极端宽排超预算回退（不缩字号）；② 缺 CJK 字体环境预算自适应（可用字体屏蔽模拟）。
3. **F1**：去掉 `test_real_dense_diagram_default_view_is_legible_at_720` 末尾恒真的 390px 凑数断言（或换成有信息量的断言）。
4. **F5**：X6 issue 文件 §1.2「非密图渲染与此前一致」措辞过强——改为「预算内图换行文本不变；分组画布间距整体收紧」。

## Acceptance criteria

- [ ] 四项逐条落实；新增边界用例 mutation 有牙。
- [ ] X6 已合并行为零改动（纯文档/测试项，不改渲染逻辑）；全量 pytest 绿。

## Blocked by

无。

## 领地

- 独占：`graph2note/diagrams/matplotlib_renderer.py`（仅 docstring）、`tests/test_diagram_render_groups.py`、X6 issue 文件。
- 禁止：渲染逻辑改动、`_layout.py`。

## Comments

- 小项，适合与 Z1/Z4/Z5 并行派发。
