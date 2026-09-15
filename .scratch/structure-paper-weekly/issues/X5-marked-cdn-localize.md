# X5 — marked.js 的 jsdelivr CDN 依赖本地化（离线可用性）

Status: ready-for-review

来源：D 轨 T-audit/阶段2 发现，记录于 `handoffs/D3-diagram-render.md` §6-诚实限制 3；`/tmp/spw-final-vision-report.md` §5-5；BOARD T-vision-final 行遗留指针「jsdelivr-marked 本地化」。属 D 轨遗留（X 轨）。

## What to build

`graph2note/webstatic/index.html` 从 `cdn.jsdelivr.net` 加载 `marked@4.3.0/marked.min.js`（同时 KaTeX 0.16.9 的 CSS/JS 也来自同一 CDN）。离线或受限网络下文档/周报预览显示「marked 未能加载」（`onerror="window.__mdMissing=1"` 仅降级，不解决可用性）；AO 桌面浏览器面板无网络，前端验证只能靠 Playwright + CDN shim。

要求：把 marked 本地化（vendor 到 `graph2note/webstatic/`），使 Markdown 预览在离线时可用；KaTeX 是否一并本地化在裁决中说明（可选）。

注意：`tests/test_graph_layout.py::test_zero_build_red_line_holds` 断言 CDN 串 `https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js` 恰好出现 1 次（U4 零构建红线），本地化必须同步更新该断言/说明，且不得引入构建步骤。

## Acceptance criteria

- [x] marked 以 pinned 版本（4.3.0）本地 vendor 进 `graph2note/webstatic/`（如 `vendor/marked.min.js`），`index.html` 改引本地路径；保留加载失败降级路径与 `window.__mdMissing` 语义。
- [x] 版本 pin 语义不变（v4 string signature 与 image renderer 兼容注释仍成立）；不引入打包/构建步骤。
- [x] 更新 `tests/test_graph_layout.py` 的 CDN 断言为零构建红线的新表述（本地模块 + 无新增 CDN），并说明 KaTeX 处置（本地化或保留 CDN + 理由）。
- [x] 离线验证：阻断外部网络下加载应用，文档预览 Markdown 正常渲染（无「marked 未能加载」）；node DOM 契约套件与全量 pytest 绿。
- [x] 若 KaTeX 保留 CDN：以 `onerror` 降级 + 文案说明；若一并本地化：体积与 license 记录在 Comments。
- [x] 第三方 license 合规：vendor 文件带版本与来源注释。

## Blocked by

无。若同时要离线 KaTeX，则需额外裁决（数学公式离线渲染范围）。

## 领地

- 独占：`graph2note/webstatic/index.html`（script 引用行）、`graph2note/webstatic/vendor/*`（新）、`tests/test_graph_layout.py`（仅该断言）、相关前端测试。
- 禁止：`app.js` 视图逻辑、I 轨 `upload.js`/`document.js` 行为改动（除引用路径必要调整）。

## Comments

- 出处原文（`handoffs/D3-diagram-render.md` §6-3）：「AO 桌面浏览器面板无网络（marked/KaTeX 来自 CDN），面板内预览显示『marked 未能加载』；前端验证用 Playwright + CDN shim 走真实 `document.js`」。
- `tests/test_graph_layout.py::test_zero_build_red_line_holds` 同时断言「U4 adds no CDN dependency and no build step」——本地化方向与该红线一致，改的是断言的具体来源串。

### 交付记录（X5，dev/X5-marked-localize）

- **marked 本地化**：`graph2note/webstatic/vendor/marked.min.js`（49,718 B，sha256 `c68075672d976e4777390560baa112194855bd4404b13647da4855aae1f9360c`），与 npm `marked@4.3.0` tarball 内 `marked.min.js` 逐字节一致（tarball sha512 与 registry `dist.integrity` 比对通过），也与原 CDN `https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js` 逐字节一致（同 sha256）。`index.html` 改为 `<script src="/static/vendor/marked.min.js" onerror="window.__mdMissing=1">`，`onerror` 与 `window.__mdMissing` 语义保留。承诺不改上游文件字节，文件自带 `marked v4.3.0 … (MIT Licensed) https://github.com/markedjs/marked` 版本/来源 banner。
- **license / 体积**：`vendor/marked.LICENSE.md`（marked 的 MIT 许可原文，2,942 B）+ `vendor/marked.README.md`（版本、来源、integrity/sha256、取用命令、升级步骤）。无 LICENSE 变更以外的体积记录：vendor 目录合计 ≈ 55 KB。
- **零构建红线**：`tests/test_graph_layout.py::test_zero_build_red_line_holds` 不再断言 jsdelivr 串，改为断言（1）sources 中不存在任何 marked CDN 引用、（2）`/static/vendor/marked.min.js` 恰好出现 1 次且文件存在、（3）banner 含 `marked v4.3.0` + `MIT Licensed`；仍断言 `/static/app.js` 与「本地模块、无构建步骤」。`static_js()` / `/static` 挂载照旧，未引入打包/构建步骤。
- **KaTeX 裁决**：保留 CDN 0.16.9 pin。理由：本地化需同时携带 `katex.min.css` + `katex.min.js` + `auto-render.min.js` 及 60+ 个字体文件（≈1 MB）并改写 CSS `url()`，比 marked 大一到两个数量级，且数学公式只是次要预览通道。处置：三个 KaTeX 资源全部加 `onerror="window.__katexMissing=1"`（CSS link 也加），失败时预览只跳过公式、Markdown 仍渲染，理由与文案写在 `index.html` 注释。
- **离线验证（真实浏览器，阻断外网）**：`Chromium --headless=new` + `--proxy-server=127.0.0.1:9 --proxy-bypass-list=127.0.0.1`（外网全部不可达）+ CDP `Network.setBlockedURLs *cdn.jsdelivr.net*`，加载本地 app（uvicorn + 43 文档种子库）后全部通过：外网 CDN fetch 失败；`window.__mdMissing` 未设置；`window.marked.parse` 可用；resource timing 中无任何 marked CDN 请求、`/static/vendor/marked.min.js` 来自本机 origin；`marked.parse` 渲染标题/粗体/列表正确；`renderer.image` 仍收到 v4 `(href,title,text)` 字符串签名；`#doc/doc-00` 真实文档预览渲染出「线性代数讲义 / 种子文档…」且 HTML 无「未能加载」；KaTeX 因外网被阻断置位 `__katexMissing=1` 但预览不受影响。
- **测试**：全量 `pytest -p no:warnings` → `1207 passed`，EXIT=0（测试数不变，未新增测试，红线断言加强即可覆盖）。
- **改动文件**：`graph2note/webstatic/index.html`、`graph2note/webstatic/vendor/{marked.min.js,marked.LICENSE.md,marked.README.md}`（新）、`tests/test_graph_layout.py`。未触碰 `app.js` / `document.js` / `upload.js` 行为，未触碰 `.scratch/baseline-and-next-iteration/**`。
