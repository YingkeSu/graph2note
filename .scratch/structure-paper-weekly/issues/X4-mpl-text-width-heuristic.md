# X4 — mpl 字宽启发式「1 unit = 半 em」低估中英混排约 12%

Status: ready-for-review

来源：`/tmp/review-spw-D5b-verdict.md` §6-F1；BOARD D5b 行残留 F1；`/tmp/spw-final-vision-report.md` §5-3。属 D 轨遗留（X 轨）。

## What to build

`matplotlib_renderer._text_size_in`（分组路径据以定节点框宽）复用仓库既有「1 unit = 半 em」启发式，对中英混排 + 全角标点**低估约 12%**，分组路径按该估值定框宽、仅余 `2×0.07in` pad，导致文字越出自身节点框。

实测（`/tmp/review-spw-D5b-verdict.md` §6-F1）：live02 节点 `n7`（`LLM 直接转？OCR？路由？`）文字 layout bbox **207px > 自身节点框 201px**（figsize 12×8 @120dpi，画布 1440px），超框 3.0px；像素级复核（`harness/pixel_ink.py`）真实字形 ink 只在**左侧越过框线 1px**（框线线宽 2px），即「文字贴边」。live02inc 另有 2 个节点余量 **0.1px**（零安全裕度）。**不构成 artist 相交**（节点间/文字间/标题压框均为 0），属「文字压边」类残留。

要求：把度量换成**真实 font metrics**（如 `matplotlib.textpath.TextPath` 或 `RendererAgg.get_text_width_height_descent`），或在 `_text_size_in` 估值上加固定裕度，使文字不越自身框。

## Acceptance criteria

- [ ] 复现 live02 `n7` 超框 3.0px bbox / 1px ink（D5b reviewer 口径），写进 Comments。
- [ ] 修复后同口径：三张 live（01/02/02inc）**文字越出自己节点框 = 0**，最小余量 > 0（建议 ≥1px）。
- [ ] 若采用真实 font metrics：CJK 字体回退链（Hiragino Sans GB 等）仍成立，且不引入 `findfont` 警告（D5b 后为 0，不得回退）。
- [ ] 布局不回退：grouped golden 逐字段对照、扁平路径逐字节 SHA256 同；终检 §3 的 artist 相交五项维持 0/0/0。
- [ ] 性能可接受：密图（01=23 节点）渲染耗时不显著恶化（记录前后对比）。
- [ ] mutation 有牙：把 pad/度量改回旧值新断言变红。
- [ ] 全量 `pytest -p no:warnings` 绿。

## Blocked by

无（与 X3 同文件，建议串行或同一 worker 协调）。

## 领地

- 独占：`graph2note/diagrams/matplotlib_renderer.py`（`_text_size_in` 及调用点）、对应新测试。
- 禁止：graphviz 渲染器、扁平 PNG golden 锁、I 轨文件。

## Comments

- D5b verdict §6-F1 根因原文：「`_text_size_in` 复用仓库既有『1 unit = 半 em』启发式，对中英混排 + 全角标点会低估约 12%，而分组路径按该估值定为框宽（仅余 2×0.07in pad）」。live02inc 另有 2 个节点余量 0.1px。
- 终检 §5-3：「F1 文字贴边残留 ... 本轮同口径（2px slack）**未复现**」——即残留按原指针保留，未消除。
- 建议非 Required：D5b 原文「把度量换成真实 font metrics（或在 pad 上加固定裕度）」。
- 交付记录（branch `dev/X3X4-mpl-layout` @ `b74f0cc`）：Status → ready-for-review。
  - 复现（D5b reviewer 口径 `/tmp/rev-d5b/harness/fit_check.py`，main `e6009fc` 树）：live02 节点 `n7`（`LLM 直接转？OCR？路由？`，折行 2 行）文字 layout bbox **207px > 自身节点框 201px**（+3.0px 越框）；live02inc 另有 2 节点余量 +0.1px（零安全裕度）。
  - 修复（`_text_size_in` 及调用点）：宽度改用真实 Agg font metrics（`RendererAgg.get_text_width_height_descent`，字体族与绘制文本同源 rcParams，CJK 回退链不变），高度保留原 1.25em 行盒模型（实测 matplotlib 多行 `linespacing`≈1.2em，用真实字形高会让折行文字竖向溢出）；组标题用其所绘粗体 face 的 `FontProperties` 度量。
  - 修复后同口径：live01/02/02inc **文字越出自身节点框 = 0**，最小余量 **6.6px**（live02 n7 框 220px vs 文字 207px）≥1px。
  - CJK 回退 / warning：`/tmp/rev-d5b/harness/bold_check.py` → 组标题 family `Hiragino Sans GB` weight 600，`font_manager` WARNING+ **0**、findfont/weight warnings **0**；`test_group_title_does_not_degrade_weight_silently` 通过。
  - 布局不回退：grouped golden 逐字段、扁平路径逐字节 SHA256 同；终检 §3 artist 相交五项维持 **0/0/0**（`/tmp/spw-final/render-X3X4-r2/`）。
  - 性能：01 密图（23 节点）5 次均值渲染 base 252.5ms → 分支 185.5ms，无恶化（`_text_metric_renderer` 惰性单例）。
  - mutation 有牙：main `e6009fc` 树上 `test_text_size_uses_real_metrics_not_half_em` 与 `test_node_text_has_positive_slack_inside_its_own_box` 红。
  - 全量 `pytest -p no:warnings`：分支 **1224 passed**。
