# Handoff S3 — 版本对比视图（编辑器内）

Branch: `dev/s3-version-diff`（自本地 `main` = `1acad49` 新建；已含 `merge: S1` `582aa61`、
`merge: S2` `57bd28a`、`merge: U3` `6272463`、`merge: P2` `9a6890f`）
Issue: `.scratch/usable-product-iteration/issues/S3-version-diff-ui.md` · Status → in-review

## 1. 一句话结论

编辑器侧板里的版本索引升级为**版本切换器**（时间 / 来源 / diff 徽标，消费 S2 版本链）；编辑器内新增
**只读版本对比覆盖层**：任选两版（默认最新 vs 前一版），按 **S1 块级锚点** 并排渲染 Markdown 高亮
（新增绿 / 删除红 / 修改黄 / 移动蓝）、两版 `preprocessed.png` 并排（复用 U3 大图查看器）、模板化
自然语言摘要条（**零模型调用**，数字与 S1 `DiffReport` 同源）。点击变更块可定位到当前版本对应块。
查看历史版本永远只读，并有显眼的「历史版本（只读）」标识与「回到最新版」。全离线测试，零真实网络 /
零 LLM 调用。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/versiondiff.py`（新，核心） | `summarize_diff(DiffSummary)->[str]`（纯模板拼接、零模型、零 IO）；`build_compare(store, doc, a, b)` 调 S1 `diff_ir` + S2 `build_version_chain`，返回两版逐块 Markdown（含 S1 `block-{index}` 锚点）+ `DiffReport` dump + 模板摘要；`resolve_selector`（id / 0-based 序号 / `prev` / `latest`）；`version_preprocessed_path`；单版/空链/同版安全态 |
| `graph2note/webapp.py` | 2 个只读 API：`GET /api/documents/{id}/diff?a&b`（404 / 422 语义）、`GET /api/documents/{id}/versions/{vid}/preprocessed`（每版原图；`working-copy` 复用最新版） |
| `graph2note/webstatic/js/version_diff_core.js`（新，纯函数） | diff 徽标（`+3 −1 ~2`，移动 `⇄n`）、行对齐 `buildRows`、块高亮/锚点/`data-locate` 单元格、版本列头（历史/当前徽标 + 原图）、摘要条、切换器列表、只读提示 —— 全部字符串拼装，Node 可直接断言 |
| `graph2note/webstatic/js/views/version-diff.js`（新） | 侧板切换器（拉 S2 版本链、diff 徽标、点击选择、历史版本只读提示 + 回到最新版）；`#diff-view` 覆盖层（两版选择器 / 交换 / 摘要条 / 空态 / 只读徽标 / 并排块高亮 / 原图 / 点击定位 / Esc 关闭）；`configureVersionDiff` 注入 U3 大图查看器与 marked 管线（无循环依赖） |
| `graph2note/webstatic/index.html` | `#doc-main` 内新增 `#diff-view` 覆盖层（不改 U3「工具条 + 三栏」主轴）；`#version-panel` 增加 `#version-compare` 与 `#version-readonly-note` |
| `graph2note/webstatic/js/views/document.js` | `renderDocument` 挂载 `renderVersionPanel`、deep link 开对比/开侧板；`openImageViewer(src)` 支持指定图片源（版本原图复用大图查看器）；Esc 优先关对比；`handleEditorShortcut` 接线。其余（标签/集合/元数据/autosave/A1 provenance）逐行未动 |
| `graph2note/webstatic/js/router.js` | 兼容扩展 commit-ish 子路由：`#doc/<id>/diff[/<a>[/<b>]]`、`#doc/<id>/versions`（无子路由时行为不变） |
| `graph2note/webstatic/js/state.js` | 元素注册 +16 行（对比覆盖层相关，无行为改动） |
| `graph2note/webstatic/style.css` | `.diff-*` 覆盖层/行列/高亮/定位闪烁、`.version-item` 按钮化 + 徽标 + 只读提示样式 |
| `tests/test_versiondiff.py`（新，14 项） | 纯模板摘要（空态/逐 op 数字与报告一致/纯拼装）+ `build_compare` 与 `diff_ir` **同 fixture 逐字对比**、默认 latest vs prev、块锚点/Markdown、任意两版/同版空 diff、单版/空链、编辑头、**零模型调用**、选择器词表 |
| `tests/test_versiondiff_api.py`（新，11 项） | API 契约（payload 形状、统计与引擎一致、选择器/交换/同版、单版安全、编辑头、404/422、只读性）+ 每版原图端点 + 静态接线 + Node harness 运行器 |
| `tests/version_diff_dom.mjs`（新） | Node DOM 行为 harness（自持轻量 DOM shim + 录制 fetch）：切换器徽标/只读态、对比两选择器/块高亮/两版原图/摘要条、点击定位（`.locate-flash` + `scrollIntoView` + 状态反馈）、空 diff/单版安全态、Esc、deep link 解析 |
| `tests/taxonomy.py` / `docs/testing.md` | `test_versiondiff → ir`、`test_versiondiff_api → webapp`（integration）；映射表补登 |
| `.scratch/usable-product-iteration/evidence/` | `version-diff-before.png`（main 编辑器）、`version-diff-after.png`（对比覆盖层 1440×1000）、`version-diff-switcher.png`（切换器），均 `graph2note visual-qa capture` |

**未改**：S1 `semantic/`、S2 `evolution.py`、U3 既有编辑器行为（标签/集合/元数据/autosave/A1 provenance）、
U2/U4/U5/P2/P3 视图；未改 `ask.js`/`pdf.js`；未合并 main、未 push、未自审。

## 3. Key decisions

- **复用而非重造 diff**：对比的块归属/统计/锚点全部来自 S1 `DiffReport`；`graph2note/versiondiff.py`
  不实现任何文本对齐算法。S2 的版本链只提供相邻版 diff 摘要；**任选两版** 的对比在 backend 调
  `diff_ir(a_ir, b_ir)` 现算（S2 契约未变）。
- **块级并排用「行」而不是两个独立滚动列**：`.diff-row { display:grid; grid-template-columns:1fr 1fr }`，
  每个 `BlockChange` 一行。这样两列天然对齐，且「added 只有副栏 / removed 只有主栏」用空占位单元格表达。
- **渲染粒度 = IR 块**：每块用既有确定性 `render_markdown`（单块 `DocumentIR`）渲染为独立 Markdown 片段，
  前端套 `id="{side}-block-{index}"` + `data-block-index` + `data-locate`。既保证「Markdown 渲染级」，
  又保证块归属严格等于 S1 的 `index`（不重新发明文本 diff 的块边界）。
- **模板摘要放在 backend**：`summarize_diff` 是唯一的自然语言来源（口径 `修改 2 个段落、新增 1 个公式`），
  API 直接下发 `summary_lines`；前端只排版。数字直接取 `DiffSummary.by_op/by_type`，因此与 S1 不可能不一致
  （AC3 同 fixture 断言 `payload["report"] == diff_ir(...).model_dump()`）。
- **零模型调用边界**：`versiondiff` 不 import 任何 gateway/llm/网络模块（静态测试）；编辑头（未提交
  编辑）的 IR 用既有确定性 `vlm._markdown_to_ir` 投影（S2 亦用此路径，非模型调用）。测试用 monkeypatch
  `vlm.call_ir` 抛错仍跑通。
- **只读红线**：对比覆盖层是 `role="dialog"` 只读层，无任何编辑控件；查看历史版本时侧板出现
  `#version-readonly-note`（「🔒 正在只读查看历史版本 v1；编辑始终作用于最新版（v3）。回到最新版」），
  覆盖层列头也有「历史版本」徽标。Markdown 编辑器始终指向最新版 —— 旧版静默回滚不可能发生。
- **U3 组件复用**：版本原图点击 → U3 大图查看器（`openImageViewer(src)` 新增加可选 src 参数，无 src 时
  行为与 U3 完全一致，含 `/original` 回退）；block Markdown 走 U3 的 marked + KaTeX 管线（经
  `configureVersionDiff` 注入，避免 `document.js ⇄ version-diff.js` 循环 import）。
- **对 U3 测试零回归**：`renderVersionPanel` 用 try/catch 包裹版本链请求，失败时保留 U3 原生版本索引；
  U3 的 Node harness（fetch 会在未知路由抛错）因此不需改动即通过。对比覆盖层挂在 `#doc-main` 内，
  U3 的「主轴 = 工具条 + 三栏」结构断言不变。
- **deep link**（顺手且有用）：`#doc/<id>/diff[/<a>[/<b>]]` 直接打开对比（a/b 支持 id、序号、`prev`/`latest`）；
  `#doc/<id>/versions` 打开侧板切换器。二者为 `parseHash` 的**追加分支**，无子路由时返回对象与 U1 完全一致。

## 4. AC 逐条证据

| AC | 证据 |
|---|---|
| 版本切换器展示版本链（时间/来源/diff 徽标）；历史版本只读 + 明显标识 + 引导回最新版 | `test_versiondiff_api.py::test_compare_view_markup_and_assets_served`（`#version-compare`/`#version-readonly-note` 存在）；`version_diff_dom.mjs`：切换器含两版 id、`version-item current`、`version-diff-badge`、`#version-info`「第 2 版」；`selectVersion(v1)` 后 `#version-readonly-note` 含「只读查看历史版本」「回到最新版」按钮、`#diff-readonly` 含 v2 引导；`version-diff-switcher.png` / `version-diff-after.png` |
| 对比视图两版选择器、并排块级高亮、原图并排、摘要条齐备；1440×1000 截图 | `version_diff_dom.mjs`：`#diff-select-a/b` 列出两版、`[data-block-index="1"].diff-modified`、`.diff-unchanged`、两版 `.../versions/<vid>/preprocessed` 图片各 1、`#diff-summary` 含「小幅改动」「修改：1 个段落」「变更 1/4 块」；真实 Chrome `--dump-dom` 校验 9/9（含 marked 渲染出的 `<h1>香农编码`、两版原图、摘要、只读提示）；`version-diff-after.png`（1440×1000） |
| 摘要模板拼接（无模型调用）；统计与 S1 DiffReport 一致（同 fixture） | `test_versiondiff.py`：`test_summarize_diff_numbers_come_from_the_report`、`test_summarize_diff_is_pure_string_assembly`、`test_compare_payload_matches_diff_ir_exactly`（`payload["report"] == diff_ir(...).model_dump()` 且 `summary_lines == summarize_diff(...)`）、`test_compare_makes_no_model_calls`、`test_versiondiff_module_has_no_network_or_model_imports`；`test_versiondiff_api.py::test_diff_endpoint_stats_match_diff_engine` |
| 点击变更块定位到最新版本编辑器对应块（DOM 断言） | `version_diff_dom.mjs`：点击 A 栏变更块 → `[data-block-index="1"].diff-latest.locate-flash` 存在、`scrollIntoView` 被调用、`#status-text` 含 `block-1`；当前版本已删除的块明确提示「当前版本中不存在第 N 块」 |
| 单版本 / 空 diff（两版相同）安全态 | `test_versiondiff.py::test_compare_same_version/单版/空链`；`test_versiondiff_api.py::test_diff_endpoint_single_version_safe_state`、`test_diff_endpoint_selectors_swap_and_same_version`；`version_diff_dom.mjs` 断言 `#diff-empty` 文案「两版内容一致」「只有 1 个版本」 |
| 离线 DOM 断言覆盖切换/对比/定位主路径；既有编辑器测试不回归 | `version_diff_dom.mjs`（切换器 + 只读 + 对比 + 定位 + 安全态 + Esc + deep link）；`editor_workspace_dom.mjs`（U3）**未改动即通过**；全量 `uv run pytest` 722 passed（基线 697 + 25） |

## 5. 验证

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-41
uv run pytest tests/test_versiondiff.py tests/test_versiondiff_api.py   # 25 passed
uv run pytest -m "webapp or ir or workspace or cli"                     # 290 passed
uv run pytest                                                           # 722 passed, 0 failed (106.10s)
node tests/version_diff_dom.mjs    # version_diff_dom: all assertions passed ✓
node tests/editor_workspace_dom.mjs  # U3 harness 未改动通过 ✓
node tests/router_routes.mjs         # 未回归 ✓
```

真实浏览器校验（headless Chrome `--dump-dom`，临时 seed 3 版本文档，`GRAPH2NOTE_STORAGE` 指向临时目录）：
`#doc/doc-s3/diff` → compare open / summary / added+modified 高亮 / 两版原图 / diff 徽标 / 只读提示 /
marked 渲染 `<h1>` / 块锚点，全部 OK。

**AC 覆盖统计**：新增 25 项测试（14 pure + 11 API/harness），全离线、零真实网络 / 零 LLM。

## 6. 边界 / 未尽事项

1. **历史版本的图片附件**：对比视图的块 Markdown 走既有 marked 资产改写（指向**文档级** `assets/`，即最新版
   资产目录），历史版本 IR 中引用的 `diagram/image` 若仅存在于该版 `versions/<vid>/assets/`，图片可能 404；
   文本/公式/表格块的对比不受影响。原图对照已按版本正确（`versions/<vid>/preprocessed.png`）。若需要
   逐版附件，可在后续把 `/assets` 端点参数化到版本目录。
2. **LIS 移动块的展示**：S1 的 `moved` 用蓝色左边框；`modified` 与 `moved` 的复合情况按 S1 单一 op 字段
   呈现（S1 handoff §8.2 的已知边界）。
3. **切换器默认收起**：侧板继承 U3 的「默认收起」，因此首屏看不到切换器（需点「信息」/⌘/）。deep link
   `#doc/<id>/versions` 可直接打开侧板。
4. **对比覆盖层是文档级弹层**：打开时覆盖三栏（`z-index:30`，低于大图查看器 40 / toast 50）；关闭后
   回到编辑器。未做「第四栏常驻」形态（桌面 1440 下弹层信息密度更合适）。
5. **窄屏**（≤900px）仍为 best-effort，未做窄屏专项验收（沿草案主场景 ≥1280）。
6. **未改 S1/S2 契约**：`versiondiff` 只消费 `graph2note.semantic` 公开面与 `evolution` 公开函数；
   `webapp.py` 仅新增两个只读路由。
7. 未 push、未合并 `main`、未自审（按协议推送/合并时机归维护者）。

## 7. 相关文件

- 实现：`graph2note/versiondiff.py`、`graph2note/webapp.py`、`graph2note/webstatic/js/version_diff_core.js`、
  `graph2note/webstatic/js/views/version-diff.js`、`graph2note/webstatic/index.html`、
  `graph2note/webstatic/js/views/document.js`、`graph2note/webstatic/js/router.js`、
  `graph2note/webstatic/js/state.js`、`graph2note/webstatic/style.css`
- 测试：`tests/test_versiondiff.py`、`tests/test_versiondiff_api.py`、`tests/version_diff_dom.mjs`、
  `tests/taxonomy.py`、`docs/testing.md`
- 证据：`.scratch/usable-product-iteration/evidence/version-diff-{before,after,switcher}.png`
- 上游：`handoffs/S1-ir-block-diff.md` §6、`handoffs/S2-evolution-anchoring.md` §5、`handoffs/U3-editor-workspace.md` §3
- 下游：无（本轮 S3 为 Semantic track 收尾）

## Suggested skills

- `impeccable`（product register）：若要继续打磨对比覆盖层的信息密度 / 空态文案 / 移动块配色。
- `diagnose`：若「点击定位不滚动」或「历史版本误触发保存」，沿 `locateBlock` / `saveMarkdown` 链定位。
