# D3 — 渲染与前端呈现（handoff）

Status: **ready-for-review**
分支：`dev/D3-diagram-render`；基线：本地 `main`（ff 合并至 `916846d`，含 SPEC §1 锚点更正）
提交：7 个（见下），每逻辑单元一提交；未 push origin，未自审，未合并。

## 1. 改动清单（vs `916846d`，14 文件 +1635/−57）

| 提交 | 内容 |
|---|---|
| `677d55f` | `graph2note/diagrams/render_semantics.py`（新）：SPEC §1 dict/IR 双形态归一化器 |
| `abdbf8d` | `graphviz_renderer.py`：`cluster_*` 子图 / `rank=same`（layer）/ 组标题 / note 小字 HTML-like label / dashed 边 |
| `532827e` | `matplotlib_renderer.py`：分组背景框+组标题 / note 小字 / dashed 箭头 / `build_figure()` 可测接缝 |
| `b9e8aef` | `tests/test_diagram_render_groups.py` + taxonomy 登记 |
| `2f724e5` | `degrade.py` + `attachments.py` + `render.py`：语义流经导出链 |
| `27b1ed9` | `webstatic/assets.js`、`views/document.js`、`style.css`：结构图 figure 呈现 + 缩放 |
| `3923903` | 字号/换行可读性策略修正（ASCII 词不截断） |

越界检查：`ir.py`/`diagram.py`/`infer.py`/`_layout.py`/`_canonical.py`/`engine.py`/`index.html`/`router.js`/`api.js`/`state.js`/`digest.py`/`webapp.py`/`store.py` **未改动**（`git diff --name-only 916846d..HEAD` 已核对）。

## 2. 实现要点（对齐 SPEC §1「渲染」条）

1. **graphviz（首选引擎）**
   - `groups` → `subgraph cluster_<id>`；`kind=layer` 额外 `rank=same`（层带=同一横排），`lane`/`cluster` 仅作视觉分组；
   - 组标题 `label` + `fontsize=20`（= `GROUP_FONTSIZE` ≥ `NOTE_FONTSIZE`）；每组固定调色板（`render_semantics.group_colors`），确定性；
   - `node.note` → HTML-like label 第二行 `<FONT POINT-SIZE="14">`（普通 label 无法混字号），14 < 节点 20；
   - `edge.style=dashed` → `style=dashed`；solid 边不写 style 属性；
   - **无 groups/note/dashed 时 DOT 源码与旧渲染器逐字节一致**（测试内嵌旧实现对比 + 基线 PNG sha 锁定）。
2. **matplotlib（回退引擎）**
   - 分组背景框：`layer` 通栏横带、`lane` 通高竖带、`cluster` 成员包络框；框+组标题画在边/节点之下（zorder=0/1）；
   - note 字号 10 < 节点 13；`GROUP_FONTSIZE=13 ≥ NOTE_FONTSIZE=10`；无 note 时 box 高度公式与旧代码逐字符相同 → **无 groups/notes 的 PNG 与基线 sha 完全一致**（`e5f561dd…`，见 §5）；
   - dashed 边（线+箭头）用独立分支，solid 路径参数不变。
3. **可读性策略（回应 T-audit 阶段1 的 ~3px 字高）**
   - 渲染侧：层级块（有 groups 或 note）对长标签做 CJK 感知换行（`wrap_display_label`，ASCII 单词不截断），压缩单排宽度 → 阅读窗按宽缩放后字高更大。**未分组路径不换行，保持字节回归锁定**；`size`/`dpi` 只整体缩放、对“字宽占比”无效，故未采用；
   - 前端侧：结构图渲染产物包成 `<figure class="g2n-diagram">`（带图注），点击/Enter/Space 打开既有大图查看器（缩放/平移），并在 `style.css` 追加 cursor/边框/图注样式（**只追加**，旧选择器未动）。
4. **导出链不丢语义**
   - `DiagramSemantics` 新增 `groups`；`FileAssetWriter.write_diagram` 在此归一化一次并把 `groups/notes/dashed_edges` 记入 `results` 审计（`self.results[i][1]["semantics"]`）；
   - `render_markdown` 在块带语义时追加一行**不可见 HTML 注释**：`<!-- diagram-semantics: {"dashed_edges":[…],"groups":[…],"notes":{…}} -->`（确定性 JSON、`<`/`>` 转义为 `\u003c`/`\u003e` 防止提前闭合）。无语义的 diagram 输出与旧实现逐字节一致。
   - **导出格式说明**：图片仍是 `![caption](assets/<doc>-diagram-N.png)`；层级语义以该 HTML 注释随 Markdown（及 vault/zip 导出）保留，渲染不可见。

## 3. 与 D1/D2 的接线状态（未 rebase 到未合并分支）

- 本分支**未** `rebase` 到 `dev/D1-diagram-extract` / `dev/D2-diagram-layout`（二者未合并；调度尚未通知）。渲染器一律按 SPEC §1 JSON 形状（dict）开发，`render_semantics` 同时接受 dict 与 IR 对象，**不 import D1/D2 代码**。
- `attachments.py` 用 `inspect.signature` 探测 `engine.render_to_png` 是否支持 `groups=`：D2 合并前不传（不报错、`results` 仍记录语义），D2 合并后自动转发。**TODO（D2 合并后）**：改为无条件 `groups=` 关键字并删除探测缓存 `_ENGINE_GROUPS_SUPPORT`。
- 未知风险：D2 若改为在 engine 内预先算好几何（而非把 `groups` 透传给渲染器），需保留本分支归一化作为绘制输入；D1 若把 `note`/`style` 落到不同字段名，`render_semantics._get` 已按 `from_`/`from`、`note`、`style` 兼容，如字段名不同需加别名。
- 合并顺序 D1→D2→D3：收到「已合并」通知后执行 `git rebase main`（或 merge），跑全量 + 用真实 `test-images` 三图重跑锚点渲染，并在此文件补记。

## 4. 渲染效果证据（/tmp，offline fixture）

> D1/D2 未合并，锚点用**手写 SPEC §1 fixture**（非真实 VLM 产物），仅证明渲染层行为；真实三图的复验归 T-audit/T-vision。

- `/tmp/spw-D3/anchors/`（graphviz + matplotlib 各 3 张，均 re-render 字节一致）
  - `01-requirements-arch.*.png`：3 条 layer 横带 + `macmini` note「亮点：Critical Path 优化 ☆」（`POINT-SIZE=14`）
  - `02-digitize-pipeline.*.png`：主线 lane + 旁注 cluster + 2 条 dashed 旁注边
  - `02-digitize-pipeline-increment.*.png`：2 个独立 cluster（原子/增量），**无** `rank=same` → 左右两流程保持可分辨（结构断言通过）
  - 结构断言输出：`/tmp/spw-D3/anchor-output.txt`
- 前端：`/tmp/spw-D3/diagram-figure-1440.png`（文档视图 figure + 图注）、`/tmp/spw-D3/audit/*.png`（33 张路由截图）、`/tmp/spw-D3/audit/audit.json`
- 复现脚本（/tmp，非仓库）：`seed_storage.py`、`render_anchors.py`、`verify_diagram_figure.mjs`、`pw-shim.mjs`

## 5. 测试证据

环境：本 worktree 的 `.venv` 只装了基础依赖，故用主仓 venv + `PYTHONPATH` 指向本 worktree：
`PYTHONPATH=$PWD /Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest …`

- `pytest -q -p no:randomly -W ignore`（**全量**）：**exit 0**，无 failed/error。（本环境下 pytest 的末行 "N passed" 被某测试的 stdout 捕获吞掉，仅见进度点；退出码为准。）
- 新增测试：`test_diagram_render_groups.py` **18 passed**、`test_diagram_semantics_export.py` **12 passed**、`test_diagram_presentation.py` **4 passed**。
- Node：`node tests/diagram_presentation.cjs` ✓、`node tests/assets_rewrite.cjs` ✓。
- 回归锁定：
  - graphviz 无 groups → DOT 源码 == 内嵌旧实现（`test_graphviz_ungrouped_source_matches_legacy_renderer`）；
  - matplotlib 无 groups/notes → PNG sha == 基线 `e5f561dd3056cedf61d4fd0626141c01c7f26662d1a97021e799401952fb3ced`（matplotlib 3.11.1；版本不符时 skip 并说明）；
  - 无分组 diagram 的 Markdown 输出逐字节不变（`test_flat_diagram_output_is_unchanged_regression`）。
- 前端巡检（brief 指定）：
  `PLAYWRIGHT_MODULE=<…>/playwright/index.js node scripts/frontend_audit.mjs http://127.0.0.1:8795 /tmp/spw-D3/audit`
  → `{"checks": 33, "findings": []}`（33 路由×宽度：0 pageerror、0 横向溢出、0 控件裁切）。
- 文档视图端到端（Playwright，离线拦截 CDN 的 marked 为最小 v4-like shim，走**真实** `document.js` 路径）：figure 渲染 ✓、`img` 指向 `/api/documents/…/assets/…-diagram-0.png` ✓、图注 ✓、figure 边框/`cursor:zoom-in` ✓、普通图片仍是裸 `<img>` ✓、点击打开大图查看器且 src 为该图 ✓、0 runtime error。

## 6. 诚实限制

1. **AO 桌面浏览器面板无网络**：index.html 的 marked/KaTeX 来自 CDN，预览在面板内显示「marked 未能加载」，故面板内无法直接看到 figure；已用 Playwright + CDN shim 走真实代码路径验证（§5），并在 AO 面板确认无 pageerror。
2. 锚点是**手写 fixture**，不代表真实 VLM 抽取质量；真实三图复验需 D1/D2 合并后由 T-audit/T-vision 执行。
3. `PLAYWRIGHT_MODULE` 需指向 `…/node_modules/playwright/index.js`（Node 25 拒绝目录 ESM import；brief 给的目录路径会 `ERR_UNSUPPORTED_DIR_IMPORT`）。另建了 `/tmp/spw-D3/pw-shim.mjs` 供 `scripts/frontend_audit.mjs` 使用。
4. matplotlib CJK 组标题 `fontweight="bold"` 在 macOS Arial Unicode 上会打印 `findfont: Failed to find font weight bold`（回退 400），仅日志噪音，不影响产物。
5. `test_matplotlib_ungrouped_png_matches_baseline_golden` 的 sha 与 matplotlib 版本绑定（PNG 内嵌版本串），换环境会 skip。
6. `attachments.py` 除 `DiagramSemantics` 外还改了 `FileAssetWriter.write_diagram`（brief 任务清单 4 要求 groups 流经导出链所必需，改动最小：签名探测转发 + results 审计字段），如需严格「仅 DiagramSemantics 段」请评审指示。

## 7. 复验建议（reviewer）

1. `PYTHONPATH=$PWD <full-venv>/bin/python -m pytest tests/test_diagram_render_groups.py tests/test_diagram_semantics_export.py tests/test_diagram_presentation.py -q`
2. `node tests/diagram_presentation.cjs`
3. 看 `/tmp/spw-D3/anchors/*.png`（若被清理，跑 `/tmp/spw-D3/render_anchors.py` 重生成）
4. 关注点：无分组路径字节回归、sidecar 注释是否为可接受的导出格式、D2 合并后的 `groups=` 接线。
