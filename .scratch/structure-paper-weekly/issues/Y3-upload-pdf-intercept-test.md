# Y3 — upload.js PDF 拦截缺行为级测试

Status: ready

来源：`/tmp/review-spw-P1-verdict.md` §3/§6-R1；`/tmp/spw-P1-done-report.md` 风险节；BOARD P1 行残留「R1 upload.js PDF 拦截仅源码断言（守卫反转不红）」。属 I 轨遗留（Y 轨）。

## What to build

`graph2note/webstatic/js/views/upload.js` 的 PDF 拦截目前只有源码字符串断言（`tests/test_papers_ingest_api.py::test_upload_entry_routes_pdf_to_the_paper_pipeline` 断言 `interceptPaperFile`/`stopPropagation`/监听注册字符串存在）。P1 reviewer 的 mutation「反转拦截守卫（`interceptPaperFile` 直接 `return`，保留字符串）」**仍 17 passed（未红）**——守卫逻辑反转不会被捕。整段/注册被删会红，但行为反转不会。

要求：补行为级（node/DOM，离线）测试，锁住「哪些事件被拦截、图片路径不受影响」。

## Acceptance criteria

- [ ] 把可判定逻辑抽为可测纯函数（如 `paperFileFromEvent(event)` / `isPdfFile(file)` 的 zone 判定，或导出可注入 `el` 的 `shouldInterceptPaperEvent(event, zone)`）。
- [ ] 新增 node/DOM 契约测试（离线，无浏览器）：①zone 内 PDF `change`/`drop` → 拦截（`preventDefault`/`stopPropagation` 被调用，进入 paper 上传）；②zone 内 JPG/PNG → 不拦截（走原图片路径，事件不被 `stopPropagation`）；③zone 外事件 → 不拦截；④`drop` 的 `event.target` 为 uploadCard 子节点 → 拦截。
- [ ] mutation 有牙：把守卫反转（PDF 不拦截 / 图片也拦截 / zone 判定恒真）时新测试变红。
- [ ] 既有源码断言保留（防整段删除）；`tests/test_papers_ingest_api.py` 的静态断言不被削弱。
- [ ] taxonomy 登记新测试文件；全量 pytest 与既有 node 套件绿。

## Blocked by

无。

## 领地

- 独占：`graph2note/webstatic/js/views/upload.js`（仅 PDF 拦截段的纯函数抽取，不改图片路径）、`tests/` 内新 node 测试 + `tests/taxonomy.py` 登记。
- 禁止：`webapp.py` 后端、`papers/*`、其他 view。

## Comments

- reviewer mutation 原文：「反转拦截守卫（`interceptPaperFile` 直接 return = 放开 PDF 拦截，保留字符串）→ 仍 17 passed（未红）✗」。
- 现有拦截为 capture 阶段 `document.addEventListener("change"/"drop", interceptPaperFile, true)`；zone 判定覆盖 `event.target === el.fileInput`（change）与 `event.target === el.uploadCard || el.uploadCard.contains(event.target)`（drop）两条路径。
