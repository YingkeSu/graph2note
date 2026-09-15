# Y3 — upload.js PDF 拦截缺行为级测试

Status: ready-for-review

来源：`/tmp/review-spw-P1-verdict.md` §3/§6-R1；`/tmp/spw-P1-done-report.md` 风险节；BOARD P1 行残留「R1 upload.js PDF 拦截仅源码断言（守卫反转不红）」。属 I 轨遗留（Y 轨）。

## What to build

`graph2note/webstatic/js/views/upload.js` 的 PDF 拦截目前只有源码字符串断言（`tests/test_papers_ingest_api.py::test_upload_entry_routes_pdf_to_the_paper_pipeline` 断言 `interceptPaperFile`/`stopPropagation`/监听注册字符串存在）。P1 reviewer 的 mutation「反转拦截守卫（`interceptPaperFile` 直接 `return`，保留字符串）」**仍 17 passed（未红）**——守卫逻辑反转不会被捕。整段/注册被删会红，但行为反转不会。

要求：补行为级（node/DOM，离线）测试，锁住「哪些事件被拦截、图片路径不受影响」。

## Acceptance criteria

- [x] 把可判定逻辑抽为可测纯函数（如 `paperFileFromEvent(event)` / `isPdfFile(file)` 的 zone 判定，或导出可注入 `el` 的 `shouldInterceptPaperEvent(event, zone)`）。
- [x] 新增 node/DOM 契约测试（离线，无浏览器）：①zone 内 PDF `change`/`drop` → 拦截（`preventDefault`/`stopPropagation` 被调用，进入 paper 上传）；②zone 内 JPG/PNG → 不拦截（走原图片路径，事件不被 `stopPropagation`）；③zone 外事件 → 不拦截；④`drop` 的 `event.target` 为 uploadCard 子节点 → 拦截。
- [x] mutation 有牙：把守卫反转（PDF 不拦截 / 图片也拦截 / zone 判定恒真）时新测试变红。
- [x] 既有源码断言保留（防整段删除）；`tests/test_papers_ingest_api.py` 的静态断言不被削弱。
- [x] taxonomy 登记新测试文件；全量 pytest 与既有 node 套件绿。

## Blocked by

无。

## 领地

- 独占：`graph2note/webstatic/js/views/upload.js`（仅 PDF 拦截段的纯函数抽取，不改图片路径）、`tests/` 内新 node 测试 + `tests/taxonomy.py` 登记。
- 禁止：`webapp.py` 后端、`papers/*`、其他 view。

## Comments

- reviewer mutation 原文：「反转拦截守卫（`interceptPaperFile` 直接 return = 放开 PDF 拦截，保留字符串）→ 仍 17 passed（未红）✗」。
- 现有拦截为 capture 阶段 `document.addEventListener("change"/"drop", interceptPaperFile, true)`；zone 判定覆盖 `event.target === el.fileInput`（change）与 `event.target === el.uploadCard || el.uploadCard.contains(event.target)`（drop）两条路径。

### 交付记录（2026，dev/Y3-upload-test）

分支 `dev/Y3-upload-test`（基于 main e6009fc，未 push）。

改动：
- `graph2note/webstatic/js/views/upload.js`（仅 PDF 拦截段）：`isPdfFile`/`paperFileFromEvent` 加 `export`；抽出并导出的纯判定 `shouldInterceptPaperEvent(event, zone)`（zone 注入，change 命中 fileInput、drop 命中 uploadCard 或其子节点且文件为 PDF）；`interceptPaperFile` 改为调用该纯函数后再 `preventDefault`/`stopPropagation` + `startPaperUpload`。图片段（acceptFile/startUpload/监听注册）逐字未改，两个 capture 注册字符串保持原样。
- `tests/upload_pdf_intercept.mjs`（新，离线 DOM shim，无浏览器/网络/npm）：纯函数矩阵（`isPdfFile`/`paperFileFromEvent`/`shouldInterceptPaperEvent`，含 zone 外/非 PDF/无文件/子节点）+ 驱动真实 capture handler 的行为契约（经 `document` 分派）：①PDF `change`/`drop`（uploadCard、子节点）→ `preventDefault`+`stopPropagation`，且落 `/api/papers/import`；②JPG/PNG → 不被拦截、无 paper 上传，且 fileInput 上既有图片 handler 仍走 `/api/parse`；③zone 外 PDF → 两计数器为 0、无 paper 上传；④capture 监听注册各 1 条。
- `tests/test_upload_pdf_intercept.py`（新，node 子进程包装，node 缺失则 skip）。
- `tests/taxonomy.py`：登记 `test_upload_pdf_intercept` → `webapp`。

证据：
- 全量 `/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest -p no:warnings` → `1219 passed`，EXIT=0（基于分支点 main e6009fc 的 `--collect-only` 实测 1218，新增 1 例；任务口径的「基线 1214」早于 Y1 等后续 SPW 合并）。
- mutation 有牙（三次均红）：A `interceptPaperFile` 开头直接 `return`（放开 PDF 拦截）→ 红；B `shouldInterceptPaperEvent` 去掉 `isPdfFile` 守卫（图片也拦截）→ 红；C zone 判定恒真 `const onZone = true` → 红。
- `tests/test_papers_ingest_api.py` 未改动，其静态断言原样通过；既有 node 套件（digest/graph_interaction/paper_view 等）随全量 pytest 绿。
- 详细证据见 `/tmp/spw-Y3-done-report.md`。

截图/演示：无（纯离线前端拦截契约）。
