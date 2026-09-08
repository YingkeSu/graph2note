# 本机文档库：持久化 + 列表 + 删除

Status: in-review

## Parent

[PRD](../PRD.md)（本地持久化、保留至用户删除）；[SPEC](../SPEC.md) User Story 5、FR-014、FR-016、FR-019、DocumentRecord 实体。

## What to build

为 Web App 增加文档生命周期管理。端到端行为：解析产生的每个文档（原图预处理前后、Document IR、最新版 Markdown、附件）自动持久化到本机；文档列表页可查看、打开继续编辑；删除时全部关联数据一并移除。

- DocumentRecord 持久化在本机文件系统即可（个人自用，无数据库要求）。
- 编辑自动保存（或明确的保存动作），刷新页面、重开浏览器后内容不丢失。
- 删除需确认，且原图、IR、Markdown、附件全部移除，不留孤儿文件。

## Acceptance criteria

- [ ] 解析 + 编辑后刷新页面，从列表重新打开，Markdown 为最新编辑版
- [ ] 文档列表展示各文档（缩略图/时间）并可进入三栏编辑视图
- [ ] 删除某文档后，其全部关联文件从本机消失（含附件目录）
- [ ] 解析失败的任务不产生半成品文档记录（或可从列表清理）
- [ ] 「重新解析」产生的更新覆盖同一 DocumentRecord，不重复建档

## Blocked by

- 06-webapp-three-pane

## Handoff

`.scratch/manuscript-compiler-mvp/handoffs/07-local-document-library.md`（2026-09-08）。

## Comments

- 2026-09-08 graph2note-2：实现完成，Status → in-review。新增 `graph2note/store.py`（DocumentStore 接缝 + FileDocumentStore 文件系统持久化 + SessionDocumentStore 内存）、扩展 `graph2note/webapp.py` 文档 Endpoints（建档/列表/打开/编辑自动保存/重解析覆盖同档/删除全移/导出），前端加文档库首页与 hash 路由，含缩略图/删除/自动保存指示。修复 issue-06 遗留「同名上传全合并为一档」缺陷（`doc_id` 源自原图存储名→恒为 `original`）：改为每次上传分配稳定 `document_id` + 上传名做 title，重新解析复用同一 id→版本化更新不重复建档；失败/超时不建档。测试 `tests/test_documents.py` TestClient 全离线（golden 注入 + 同 storage 重建 app 模拟刷新），含建档/列表/编辑持久化/重开还原/删除全移/失败无半成品/重解析覆盖同档/导出/会话接缝。全套 153 passed / 2 skipped。候选版本=最小实现（新上传独立 id，同 id 合并为版本；09 感知哈希接管完整归并）。
