# Handoff — Issue 06：Web App（上传 → 三栏校对编辑 → 复制/导出）

**Status: in-review** · Track A worker：graph2note-2 · Branch：`dev/06-webapp-three-pane`
**Verified:** offline only (golden routers seeded, zero network) · 142 passed / 2 skipped

---

## 1. 核心入口 / 交付内容

- **Backend** `graph2note/webapp.py` — FastAPI app（`create_app()` 工厂）：
  - `POST /api/parse`（multipart 上传）→ `POST /api/jobs/{id}/reparse`（复用原图）→ `GET /api/jobs/{id}`（轮询状态）→
    `GET /api/jobs/{id}/original|preprocessed`、`GET /api/jobs/{id}/assets/{name}`（附件，path-traversal 防护）→
    `POST /api/jobs/{id}/export`（zip：被编辑 `.md` + `assets/` 附件 + `export-notes.json` 含 `missing_attachments`）。
  - `JobRunner`：后台线程 + `ThreadPoolExecutor` + 看门狗 `JOB_TIMEOUT`（env `GRAPH2NOTE_JOB_TIMEOUT`，默认 180s）→ 超时置 `timeout` 并给可读中文原因。解析失败置 `failed`（含 Retro 详情），成功置 `done`。终态均可 `reparse`。
  - 所有解析走 `pipeline.parse_document` + Recognition Router（`create_app(router_factory=…)` 让测试注入离线 router，永不旁路）。无密钥处理——网关自读 env/`.env`。
  - 静态前端挂载于 `/static`，`/` 渲染 `index.html`。
- **Frontend** `graph2note/webstatic/`（零构建，vanilla JS + CDN）：
  - `index.html`：上传区 → 工作中 → 三栏（预处理原图 | 可编辑 MD monospace | 实时预览）+ 底栏操作（重新解析/复制/下载）+ P1 占位（模板选择器）。
  - `app.js`：拖拽/选择上传（≤10MB、类型校验给明确中文提示）；轮询任务；三栏渲染（marked + KaTeX `renderMathInElement`）；预览失败**仅降级预览栏错误占位**，编辑不受影响；编辑器 input 防抖 180ms 实时刷新预览；复制（clipboard + execCommand 回退）；下载走 export 并提交**当前编辑后**的 markdown；重新解析 `window.confirm` 覆盖确认 + 进行中禁用（防抖）；失败/超时回到上传区带「重试解析」（复用原图）。
  - `style.css`：三栏等宽横排、响应式、深色图区等。

## 2. 验收标准对应

| AC | 状态 |
| --- | --- |
| `test-images/` 手稿经浏览器上传到下载 `.md`+附件全流程可用 | ✅ 后端全链 + TestClient 离线验证；浏览器手工路径见 §3 |
| 旋转/歪斜照片自动校正后解析（继承 03） | ✅ 管线预处理不变，Web 复用 `parse_document` |
| 编辑 Markdown 后预览实时更新；`$…$` 与表格正确渲染 | ✅ 客户端 marked+KaTeX；防抖 180ms |
| 非图、超 10MB、超时三类失败各有提示与恢复 | ✅ `415 / 413 / 400` + `timeout`；恢复=重试解析复用原图 |
| 「重新解析」覆盖确认 + 防抖 | ✅ confirm + busy 禁用 |
| 仅本机访问，无需登录 | ✅ localhost FastAPI 单用户、无鉴权 |

## 3. 验证

```bash
python3 -m pytest -q        # 142 passed, 2 skipped（全部离线，无网络）
node --check graph2note/webstatic/app.js   # 前端语法
```

**手工浏览器路径（一次性，有图即可，无 live 依赖）**：
1. `uvicorn graph2note.webapp:create_app --factory --host 127.0.0.1 --port 8000`
2. 打开 `http://127.0.0.1:8000/`，拖一张 JPEG/PNG（如 `test-images/02-digitize-pipeline.jpg`）。
3. 等三栏出现：左=预处理图，中=可编辑 MD，右=实时渲染预览。编辑 MD 改几行、插入 `$\\alpha^2$` 与一张表，看预览即时更新。
4. 点击「复制」→ 粘贴验证；「下载 .md + 附件」→ 解压核对 `.md`（含你的编辑）与 `assets/`。
5. 点「重新解析」→ 确认弹窗 → 复用时被禁用。
6. 反向验证：传 `.txt`（415）、>10MB（413）、坏 `fake.png`（415）→ 均有明确错误；`test_e2e` 注入慢路由可看 `timeout`。

## 4. 已知问题 / 风险

- **资产路径修复**：问题 03 遗留 `assets/assets/` 双层嵌套（`FileAssetWriter` 视其目录为「根」、内部拼接 `assets/<name>`，而管线把已含 `assets/` 的目录传给它）已在本交付内修复——管线改传 out-dir 为根，`assets/<name>` 在磁盘上正确解析，Web 附件服务/zip 与 CLI 语义一致。相关 e2e 断言（附件完整、`missing_attachments==[]`）保持绿。
- **img01 golden**：dispatcher 指示的帧重录（网关修复 520a0a6 合并后）在 issue 06 分支上验证：glm-5.3-flash 对 `test-images/01` 仍返回空正文（165.7s, `finish_reason=length`, completion_tokens=5000 全被推理消耗, 网关未回传 `reasoning_tokens`）→ **保留空 golden + 干净降级断言**（记录于 issue 03）。img01 全结构 Markdown 属模型能力而非网关速度，待模型升级/评估集跑批。
- **持久化**：`DocumentStore`（ABC）+ `SessionDocumentStore` 是问题 07 的**持久化接缝**（会话内存态即可，重启即失），07 明确 out-of-scope。artifacts 布局 `<storage>/<job_id>/` + `<job_id>/out/`，07 可直接接管/扫描。
- **多 worker 上限**：`ThreadPoolExecutor(max_workers=2)`，并发再高会排队；单用户本地够用。
- **CDN 依赖**：marked/KaTeX 走 CDN，离线网络不可达时预览降级为「预览库未加载」占位（编辑不受影响）；如需完全离线可后续 vendor（P1）。

## 5. 后续（可交给后续 issue）

- **09** 缺页/重复版本提示（前端两个 `.markers` 占位元素已留好）。
- **10** 交叉验证分歧标记（同一 `#marker-cv` 占位）。
- P1 模板选择器（`#template-select` disabled 占位）。
- CDN KaTeX vendor 化使预览完全离线可用。