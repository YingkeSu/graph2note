# X5 — marked.js 的 jsdelivr CDN 依赖本地化（离线可用性）

Status: ready

来源：D 轨 T-audit/阶段2 发现，记录于 `handoffs/D3-diagram-render.md` §6-诚实限制 3；`/tmp/spw-final-vision-report.md` §5-5；BOARD T-vision-final 行遗留指针「jsdelivr-marked 本地化」。属 D 轨遗留（X 轨）。

## What to build

`graph2note/webstatic/index.html` 从 `cdn.jsdelivr.net` 加载 `marked@4.3.0/marked.min.js`（同时 KaTeX 0.16.9 的 CSS/JS 也来自同一 CDN）。离线或受限网络下文档/周报预览显示「marked 未能加载」（`onerror="window.__mdMissing=1"` 仅降级，不解决可用性）；AO 桌面浏览器面板无网络，前端验证只能靠 Playwright + CDN shim。

要求：把 marked 本地化（vendor 到 `graph2note/webstatic/`），使 Markdown 预览在离线时可用；KaTeX 是否一并本地化在裁决中说明（可选）。

注意：`tests/test_graph_layout.py::test_zero_build_red_line_holds` 断言 CDN 串 `https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js` 恰好出现 1 次（U4 零构建红线），本地化必须同步更新该断言/说明，且不得引入构建步骤。

## Acceptance criteria

- [ ] marked 以 pinned 版本（4.3.0）本地 vendor 进 `graph2note/webstatic/`（如 `vendor/marked.min.js`），`index.html` 改引本地路径；保留加载失败降级路径与 `window.__mdMissing` 语义。
- [ ] 版本 pin 语义不变（v4 string signature 与 image renderer 兼容注释仍成立）；不引入打包/构建步骤。
- [ ] 更新 `tests/test_graph_layout.py` 的 CDN 断言为零构建红线的新表述（本地模块 + 无新增 CDN），并说明 KaTeX 处置（本地化或保留 CDN + 理由）。
- [ ] 离线验证：阻断外部网络下加载应用，文档预览 Markdown 正常渲染（无「marked 未能加载」）；node DOM 契约套件与全量 pytest 绿。
- [ ] 若 KaTeX 保留 CDN：以 `onerror` 降级 + 文案说明；若一并本地化：体积与 license 记录在 Comments。
- [ ] 第三方 license 合规：vendor 文件带版本与来源注释。

## Blocked by

无。若同时要离线 KaTeX，则需额外裁决（数学公式离线渲染范围）。

## 领地

- 独占：`graph2note/webstatic/index.html`（script 引用行）、`graph2note/webstatic/vendor/*`（新）、`tests/test_graph_layout.py`（仅该断言）、相关前端测试。
- 禁止：`app.js` 视图逻辑、I 轨 `upload.js`/`document.js` 行为改动（除引用路径必要调整）。

## Comments

- 出处原文（`handoffs/D3-diagram-render.md` §6-3）：「AO 桌面浏览器面板无网络（marked/KaTeX 来自 CDN），面板内预览显示『marked 未能加载』；前端验证用 Playwright + CDN shim 走真实 `document.js`」。
- `tests/test_graph_layout.py::test_zero_build_red_line_holds` 同时断言「U4 adds no CDN dependency and no build step」——本地化方向与该红线一致，改的是断言的具体来源串。
