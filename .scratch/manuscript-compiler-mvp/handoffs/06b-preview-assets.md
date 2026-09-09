# Handoff — Issue 06b：三栏预览显示重建图（assets 路径重写）

**Status: in-review** · Worker：AO fix worker · Branch：`dev/06b-preview-assets`
**Verified:** node 单测 + pytest（`295 passed, 2 skipped`，全离线，不回退）

---

## 1. 根因（一句话）

后端把重建图以相对引用 `![…](assets/xxx.png)` 写进 Markdown，前端 `app.js` 用 marked
渲染时未做任何 assets 路径处理，浏览器按页面原点解析成 `http://host/assets/xxx.png` →
404 → 三栏预览栏的架构图/流程图显示不出来；而附件端点实际在
`/api/jobs/{job_id}/assets/{name}` 与 `/api/documents/{document_id}/assets/{name}`。

## 2. 修复

- **新增** `graph2note/webstatic/assets.js`（纯函数、零依赖、UMD）：
  - `resolveAssetSrc(name, kind, id)`：仅把 **`assets/` 开头**的相对引用重写为上下文 API URL
    —— `job` → `/api/jobs/<id>/assets/<name>`、`doc` → `/api/documents/<id>/assets/<name>`；
    其余引用（外链、绝对路径、其它相对路径）原样返回不动。
  - `isAssetRef(name)` 供判定/测试。
  - CJS `module.exports` + 浏览器挂 `window.__g2nAssets`，可被 Node 直接单测。
- **改** `graph2note/webstatic/index.html`：在 `app.js` 之前引入 `assets.js`。
- **改** `graph2note/webstatic/app.js`：
  - `currentPreviewContext()`：按当前 hash/state 给出预览上下文——`doc` 路由用
    `state.docId`→doc 端点；存在 `state.jobId`（fresh-parse 上下文）→job 端点。
  - `ensureMarkedPrepared()`：一次性给 marked 装自定义 `image` renderer，把 `assets/`
    引用重写为上下文 URL，非 assets 引用走原逻辑；渲染前调用（幂等）。
  - 编辑栏/复制/导出仍用**原始 Markdown**（相对路径），语义不变。

## 3. 验证

```bash
node tests/assets_rewrite.cjs            # 断言全过（见下）
node --check graph2note/webstatic/app.js graph2note/webstatic/assets.js
python3 -m pytest -q                     # 295 passed, 2 skipped（不回退）
```

单测覆盖（`tests/assets_rewrite.cjs`）：
1. job 视图 `assets/arch.png` → `/api/jobs/<id>/assets/arch.png`
2. doc 视图 `assets/flow.png` → `/api/documents/<id>/assets/flow.png`
3. 外链 `https://…` / 绝对路径 `/api/…` 不动
4. `isAssetRef`：仅 `assets/` 前缀（大小写敏感）、null/undefined 为 false
5. 资产名经 `encodeURIComponent` 保留

**手工浏览器路径（一次性，有图即可）**：
1. `uvicorn graph2note.webapp:create_app --factory --host 127.0.0.1 --port 8000`
2. 打开 `http://127.0.0.1:8000/` →「新解析」上传
   `test-images/01-requirements-arch.jpg`（含架构图）。
3. 等待解析完成进入三栏 → 右键预览栏中的重建图「在新标签页打开」，
   地址应为 `/api/documents/<id>/assets/<name>` 且正常显示图片（修复前为 `/assets/…` 404）。

## 4. 风险 / 备注

- 预览栏依赖 `assets.js` 加载成功与 marked 可用；二者任一缺失时 renderer 不安装，
  图片引用保持原样（`ensureMarkedPrepared` 内的守卫保证不会抛错、不影响编辑）。
- 本 app 当前仅 `doc` 视图渲染预览；`job` 上下文为同构预留，逻辑已按上下文中立实现。
- 无密钥、无新依赖、零构建。