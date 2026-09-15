# W2 — 周报展示交互与导出（handoff）

Status: **ready-for-review**
分支：`dev/W2-digest-view`（基线 `main aedf2de`，W1 已合并；AO worktree 从 `2fd1f98` `--ff-only` 到 `aedf2de`，无历史改写）
日期：2026-09-15
领地：`graph2note/webstatic/js/views/dashboard.js`（独占，周报区块重写）、前端契约测试新文件
只追加：`graph2note/webstatic/style.css`（文件末尾新增 W2 段）、`tests/taxonomy.py`（+1 行测试登记，防 `test_taxonomy` 拦截）
**未动**：`graph2note/digest.py`、`graph2note/webapp.py`、`graph2note/webstatic/index.html`、`graph2note/webstatic/js/api.js` / `state.js` / `router.js`、`ir.py`、`diagram*`、`papers/*`、`.scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md`（脏文件）。
未 push；未 `find /Users/suyingke`；本地 venv 用主仓 `/Users/suyingke/Programs/OHO/graph2note/.venv`（worktree 无 `.venv`，`python -m pytest` 从 worktree 根跑，`graph2note` 解析到本 worktree）；密钥未进任何产物与提交。

---

## §0 总览（对照 issue 验收项）

| # | 验收项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 分节渲染：带 `sections` 走分节视图（节标题锚点导航），旧 meta 回退整篇；两条路径都有测试 | **达成** | `splitDigestMarkdown`（纯函数）+ `renderDigestSectioned`；旧 meta 走 `renderMarkdownInto(el.digestViewerContent, digestView.markdown)`（与 A2 完全一致）。`node tests/digest_view_dom.mjs` 同时覆盖两条路径；live 交互脚本再各验一次（1440 截图 2 张） |
| 2 | 来源跳转：节内来源 id 为可点链接路由到库内文档；失效 id 灰显/提示不炸页 | **达成** | 每节渲染 `.digest-section-sources` chips：活 id → `<a href="#doc/<id>">`（label 取库标题）；库内不存在的 id → 灰显 `<button.digest-source-missing>`，`title=库中已不存在该文档`，点击只弹 toast、不改路由。live：`doc-00` → `#doc/doc-00`；`doc-doc-missing` → 灰显 + toast，hash 仍 `#dashboard` |
| 3 | 导出：当前周报下载为 `.md`（文件名含范围与日期） | **达成** | **前端 Blob**（不新增 API 端点、不动 webapp.py）：`#digest-export` 由 JS 建在既有 `.digest-controls` 内；文件名 `weekly-digest_<from>_<to>_<created-date>.md`。live 下载事件实测 `weekly-digest_2026-09-08_2026-09-14_2026-09-15.md`，内容以 `# 本周小结` 开头且含四节 |
| 4 | 历史列表：范围/时间/模型/token-cost 摘要；空/生成中/失败三态有明确文案与可操作按钮 | **达成** | 历史项三行：范围标签 / `生成时间：…` / `篇数 · 模型 · 1,000 分隔 tokens · 模型调用 N 次｜缓存复用`，选中项 `aria-current`；`#digest-actions` 由 JS 建在状态行后：空范围=［修改范围, 再试一次］、生成失败=［重试生成, 修改范围］、读取失败=［重新读取, 修改范围］、首启空=［生成小结, 选择范围］、历史加载失败=列表内联［重试］（且不误报「还没有生成过小结」）；生成中禁用按钮 + `aria-busy` |
| 5 | 视觉/可达性沿用纸感基线：正文 ≥14px、辅助 ≥12px、对比度 ≥4.5:1；390px 无横向溢出；`frontend_audit.mjs` 3 宽度 0 溢出/0 裁切/0 pageerror | **达成** | `.digest-section-body.preview` 走既有 `.preview`（实测 15px）；辅助最小 12px；live 计算样式实测最差对比度 **5.52**（`node /tmp/spw-w2-contrast.mjs`，含 chip/链接/nav/历史/失效 chip 共 12 类）。`frontend_audit.mjs` → `{"checks":33,"findings":[]}`（1440/768/390 × 11 路由）；390px 交互后 `#digest-panel` 自身 `scrollWidth == clientWidth`、无裁切控件 |
| 6 | 前端契约测试覆盖分节/回退/跳转/导出；全量 pytest 绿；CI 不触网 | **达成** | 新增 `tests/digest_view_dom.mjs`（真模块 + DOM shim + fetch replay，无浏览器/网络）+ `tests/test_digest_view.py`（5 用例：node 套件、index.html 零改动、style 追加、双渲染路径、静态资源可服务）。全量 pytest **1192 passed**（W1 合并后 main 基线 1187 → +5） |

---

## §1 实现形状

```
meta.sections 存在 ──▶ renderDigestSectioned
                        ├─ buildDigestStats（范围内 / 选入材料 / 解析 / 新增 / 主题标签 / Inbox / 连续体 + 口径提示）
                        ├─ lead（markdown 首个 ## 之前）
                        ├─ buildDigestNav（纯 button，点击 scrollIntoView + focus，不改 hash 路由）
                        ├─ buildDigestSection × N（标题 + renderMarkdownInto(body) + 来源 chips）
                        └─ extras（`## 来源` 等未被 sections 声明的块，虚线块保留，不丢内容）
meta.sections 缺失 ──▶ renderMarkdownInto(viewer, markdown)   # 与 A2 完全相同
导出：exportCurrentDigest() → Blob → <a download>（无服务端往返）
```

- 纯函数（可 node 直测）：`splitDigestMarkdown`、`digestSectionAnchor`、`digestMetaSummary`、
  `digestLlmModeLabel`、`digestHistorySummary`、`formatTokenCount`、`digestStatsSummary`、
  `digestExportFilename`。
- 入口（供离线 DOM 测试驱动真模块）：`showDigest` / `openDigest` / `renderDigestPanel` /
  `renderDigestHistory` / `exportCurrentDigest`。
- 库索引：`GET /api/documents` 一次解析 `document_id → title`，同时用于「活/失效 id」判定；
  该请求失败时**不判定失效**（链接照常可点），面板每次渲染重置索引以便恢复。

## §2 关键设计决策（请评审重点看）

1. **导出用前端 Blob，不动 webapp.py**：`/api/digests/{id}` 已返回完整 markdown，导出无需新端点，
   领地最小；issue 允许「前端 Blob 或只读 API 端点」，此处选前者。
2. **不碰 index.html**：导出按钮与状态动作行都由 `dashboard.js` 在既有容器内 `createElement` 追加
   （`.digest-controls` 末尾 / 状态行之后）。静态测试断言 `index.html` 的 `digest-*` id 集合与 W2 前完全一致。
3. **导航不用 hash 锚点**：`href="#digest-section-…"` 会被现有 router 当作路由解析并跳走，所以用
   `<button>` + `scrollIntoView` + `focus({preventScroll})`；有测试断言点击后 `location.hash` 不变。
4. **未声明块不丢**：`splitDigestMarkdown` 把 lead、`## 来源` 等返回为 extras 并渲染（`## 来源` 用虚线块），
   声明了但 markdown 里缺的节仍给空槽（`_（本节没有可归纳的内容）_`）。
5. **R2 口径差异显式呈现**：统计条把 `stats.inbox_in_range` 标为「Inbox 本期」并附**可见文本**口径说明
   （不是只放 tooltip）：Inbox 沿用库投影，含仅缺标签；材料分区只收完全无主题/标签或显式标记者，两者不可相加。
6. **R8 同名异义显式区分**：统计条同时给「范围内 `stats.document_count`」与「选入材料 `meta.document_count`」，
   避免把范围内总数与预算裁剪后的选入数混为一谈。
7. **历史失败不误报空**：`loadDigestHistory` 失败时置 `historyFailed`，`renderDigestPanel` 据此
   跳过「还没有生成过小结」，改在历史列表内联「重试」。
8. **`llm_calls` 语义**：历史摘要里 `0` 显示「缓存复用」，>0 显示「模型调用 N 次」（承接 W1 §2-6）。

## §3 证据（可复跑）

```bash
cd <worktree>
PY=/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python

$PY -m pytest -p no:warnings                    # 1192 passed in 134.42s
$PY -m pytest -p no:warnings -q tests/test_digest_view.py    # 5 passed
node tests/digest_view_dom.mjs                  # digest_view_dom: all assertions passed ✓
```

live（离线 fixture 合成 meta.json 驱动；无模型调用、无密钥）：

```bash
# /tmp/spw-w2-storage = .scratch/frontend-loop/populated-storage 的副本 + 两个合成 digest
#   digest-w2-fixture-sectioned（4 节 + 1 个库内不存在的来源 id）
#   digest-w2-fixture-legacy（无 sections，验证回退）
GRAPH2NOTE_STORAGE=/tmp/spw-w2-storage $PY -m uvicorn graph2note.webapp:create_app \
    --factory --host 127.0.0.1 --port 8796

PLAYWRIGHT_MODULE=/Users/suyingke/.npm/_npx/9833c18b2d85bc59/node_modules/playwright/index.mjs \
  node scripts/frontend_audit.mjs http://127.0.0.1:8796 /tmp/spw-w2-audit
#   -> {"checks":33,"findings":[]}    （1440/768/390 × 11 路由，0 溢出/0 裁切/0 pageerror）

# 临时交互脚本（/tmp，未入库）：导航聚焦、活/失效来源、真实下载事件、旧 meta 回退、390px 交互后几何
node /tmp/spw-w2-interactions.mjs http://127.0.0.1:8796
#   -> w2 interactions: all checks passed (nav/focus, live+dead source links, export download,
#      legacy fallback, 390px geometry)
# 计算样式/对比度脚本（/tmp，未入库）
node /tmp/spw-w2-contrast.mjs http://127.0.0.1:8796
#   -> worstContrast 5.52；12 类元素 fontPx ≥12（正文 15）；failures []
```

截图（`/tmp/spw-w2-audit/`，非仓库产物）：`w2-dashboard-sectioned-1440.png`、
`w2-dashboard-legacy-1440.png`、`w2-dashboard-sectioned-390.png`；audit 全量 33 张亦在该目录。

> 预览：已用 `ao preview http://127.0.0.1:8796/#dashboard` adopt 该 URL 到本会话浏览器面板。
> 该 uvicorn 仍在运行（PID 97948），会话结束/评审结束后可 `kill 97948`（不 push、不影响仓库）。

## §4 测试清单

| 文件 | 变化 | 覆盖 |
|---|---|---|
| `tests/digest_view_dom.mjs` | 新增（1 个 node 套件，含 9 组断言区） | 纯函数契约（split/文件名/token/统计 chip/R2 提示）；分节渲染 + nav 顺序/计数/聚焦；活/失效来源；统计条与口径说明；导出下载（文件名 + Blob 内容）；旧 meta 整篇回退 + 历史摘要；生成中/生成失败/空范围/读取失败/历史加载失败/首启空态；`aria-current`/`aria-busy` |
| `tests/test_digest_view.py` | 新增（5 用例） | node 套件跑通；`index.html` 零改动；`style.css` 仅追加（既有 digest 规则逐字节在、新段在文末、无 <12px）；双渲染路径与导出符号在位；`/static` 服务到新代码 |
| `tests/taxonomy.py` | +1 行 | `test_digest_view` → `notes`（模块登记） |
| `graph2note/webstatic/js/views/dashboard.js` | 周报区块重写 | 见 §1 |
| `graph2note/webstatic/style.css` | 末尾追加 W2 段（57 行） | stats/nav/section/chips/extra/actions/history-error；无既有选择器改动 |

## §5 残留 / 风险（供 reviewer 决策）

- **R1 来源标题缓存粒度**：`/api/documents` 索引每次进入 dashboard 面板刷新一次；停留在面板内
  期间若库发生变化，已渲染的失效判定不会自动更新（下次进面板恢复）。不为 W2 加分项做轮询。
- **R2 大量来源 id**：某节来源很多时 chips 会换行占用高度（无折叠）。四节视图的 head 与正文仍
  `max-height` 滚动；如需折叠可作为后续优化。
- **R3 extras 渲染**：`## 来源` 在分节视图下作为虚线 extra 块保留（同时每节有 chips），存在两处
  来源展示；这是「不丢内容」与「节内可跳转」的折中，若评审认为重复，可改为只留 chips。
- **R4 旧 meta（无 sections）无导出禁用**：旧 meta 也能导出（整篇 markdown），文件名 range 缺失时
  以 `unknown` 占位（仍含日期）。
- **R5 未验证真实 W1 生成数据**：live 用的是合成 meta（含一个故意失效 id）；真实 `POST /api/digests`
  出 W1 数据由 reviewer 用真实库验证（W1 已保证 `/api/digests` 原样带 `sections`）。
- **R6 `historyFailed` 分支未在 live 覆盖**：仅 node 套件覆盖（fetch replay 注入 500）。

## §6 评审建议的最小验证路径

```bash
cd <worktree>
PY=/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python
$PY -m pytest -p no:warnings -q tests/test_digest_view.py tests/test_weekly_digest.py   # 5 + W1
node tests/digest_view_dom.mjs                                                          # 真模块 DOM 契约
$PY -m pytest -p no:warnings                                                            # 1192 passed
# mutation 建议（应有牙）：
#  1) 删掉 renderDigestSectioned 的 `if (sections.length)` 分支 → node 套件分节断言红
#  2) 把 digestSourceChips 的 missing 分支改回 <a> → 「失效 id 不导航」断言红
#  3) digestExportFilename 去掉 created 段 → 导出文件名断言红
#  4) style.css 把 .digest-source 颜色改回 #1f6feb → live 对比度脚本红（4.11 < 4.5）
```
