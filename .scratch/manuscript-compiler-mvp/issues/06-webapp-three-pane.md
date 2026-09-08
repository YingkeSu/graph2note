# Web App：上传 → 三栏校对编辑 → 复制/导出

Status: merged

## Parent

[PRD](../PRD.md)（三栏 UI、个人自用本地平台）；[SPEC](../SPEC.md) User Story 1/2/3、FR-001、FR-010~013、FR-015。

## What to build

把 CLI 链路包成本地 Web 应用（个人自用：单用户、无鉴权、仅本机访问）。端到端行为：浏览器上传手稿图片 → 自动解析 → 三栏界面（原图 | 可编辑 Markdown | 实时渲染预览）→ 复制到剪贴板 / 下载 `.md` + 附件。

- 上传校验：仅 JPG/JPEG/PNG、≤10MB，违规给明确提示。
- 预览基于客户端 Markdown + KaTeX 渲染链，支持公式与表格；预览渲染失败只影响预览栏（错误占位），不影响编辑。
- 「重新解析」复用原图，覆盖用户编辑前明确提示；请求防抖/进行中禁用。
- 解析失败/超时给用户可理解的原因与重试入口，原图不丢失（会话内）。
- 界面为模板选择器预留位置（P1）。

## Acceptance criteria

- [x] `test-images/` 手稿经浏览器上传到下载 `.md`+附件全流程可用
- [x] 旋转/歪斜照片自动校正后解析（继承 issue 03 能力）
- [x] 编辑 Markdown 后预览实时更新；公式 `$…$` 与表格正确渲染
- [x] 非图片文件、超 10MB、解析超时三类失败各有明确提示与恢复路径
- [x] 「重新解析」前有覆盖确认；连续点击被防抖
- [x] 仅本机访问即可使用，无需任何登录

## Blocked by

- 03-parse-pipeline-cli（解析链路）
- 05-diagram-render-attachments（流程图嵌入）

## Handoff

`.scratch/manuscript-compiler-mvp/handoffs/06-webapp-three-pane.md`（2026-09-08）。

## Comments

- 2026-09-08 graph2note-2：实现完成，Status → in-review。后端 `graph2note/webapp.py`（FastAPI，`create_app` 工厂可注入离线 router；DocumentStore 为持久化接缝，07 out-of-scope，会话态即可）+ 前端 `graph2note/webstatic/`（三栏：预处理原图 | 可编辑 MD | 客户端 marked+KaTeX 预览，预览失败仅降级预览栏；复制/重新解析/下载/防抖齐全；模板选择器 P1 占位）。测试 `tests/test_webapp.py` TestClient 全离线（注入 golden router），覆盖上传 413/415/400、失败与超时、zip 导出（被编辑 md+资产+export-notes）、409。修复问题 03 遗留**资产路径不一致**（FileAssetWriter 根语义 vs 管线传已含 `assets/` 目录 → `assets/assets/` 双层嵌套）：管线改传 out-dir 为根，`assets/<name>` 磁盘正确解析，Web 附件服务/zip 与 CLI 一致。img01 golden 用修复后网关（520a0a6）重录仍空，保留空 golden 与干净降级（记于 issue 03）。全套 142 passed / 2 skipped 离线。
