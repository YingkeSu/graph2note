# Handoff — Issue 07：本机文档库（持久化 + 列表 + 删除）

**Status: in-review** · Track A worker：graph2note-2 · Branch：`dev/07-local-document-library`
**Verified:** offline only（golden 注入，零网络）· 153 passed / 2 skipped

---

## 1. 核心交付

- **`graph2note/store.py`（新增）** — 持久化接缝与实现：
  - `DocumentStore`（ABC）：issue-06 作业接缝（`job_out_dir / save_original / get_original / remove`）+ issue-07 文档库
    （`list_documents / get_document / save_document / save_edits / delete_document`）。
  - `FileDocumentStore(DocumentStore)`：**文件系统持久化**（个人自用，无数据库）。布局：
    `storage/jobs/<job_id>/`（瞬态作业工作区，06 沿用）+ `storage/documents/<document_id>/`（持久记录：
    `original.<ext>`、`record.json`、`markdown.md`（**实时编辑版**）、`versions/<v>/`（不可变版本快照：
    `markdown.md / ir.json / preprocessed.png / preprocessed_raw.png / assets/ / timing.json`））。
  - `SessionDocumentStore(DocumentStore)`：同接缝、内存态（非持久），供 seam/tests 复用。
- **`graph2note/webapp.py`（改）** — 解析成功后**自动建档**（`save_document` 提交新版本），并新增长文档 Endpoints：
  - `GET /api/documents`（列表）、`GET /api/documents/{id}`（记录：当前 markdown + 版本 + 服务路径）、
    `GET /api/documents/{id}/original|preprocessed|assets/{name}`、`POST …/markdown`（**编辑自动保存**）、
    `POST …/reparse`（复用原图→新作业→更新**同一**记录加版本）、`POST …/export`（zip：被编辑 md + assets + export-notes）、
    `DELETE …/documents/{id}`（整目录移除 + 原作业工作区清除，无孤儿）。
  - 每个上传分配稳定 `document_id`（uuid 前缀）+ 上传文件名做 `title`；同一上传的重新解析复用同一 id → **覆盖更新不重复建档**；
    失败/超时**永不建档**（无半成品）。列表服务端按 `updated_at` 倒序。
- **前端** `graph2note/webstatic/`（改）— 新增**文档库首页**（缩略图/时间/版次，卡片可打开）+ hash 路由
  （`#library / #upload / #doc/<id>`）：打开文档进入三栏编辑；编辑器**防抖自动保存**（800ms post markdown，保存指示）；
  「重新解析」确认后覆盖（旧版留存历史）；「删除」确认后整档清除；下载/复制沿用。P1 占位（模板/交叉验证/缺页）保留。

## 2. AC 对应

| AC | 状态 |
| --- | --- |
| 解析+编辑后刷新页面，从列表重开，Markdown 为最新编辑版 | ✅ FileDocumentStore 持久 + 编辑自动保存；测试用「同 storage 新建 app」模拟刷新并断言还原 |
| 列表展示各文档（缩略图/时间）并可进入三栏编辑 | ✅ `/api/documents` + 卡片点击进入 `#doc/<id>` |
| 删除后全部关联文件从本机消失（含附件目录） | ✅ `delete_document` 整目录 rmtree + 清原作业工作区；测试断言 `documents/<id>` 与 `jobs/<job_id>` 均不存在 |
| 解析失败不产生半成品记录 | ✅ 仅成功后 `save_document`；非法 IR 失败测试断言列表为空 |
| 「重新解析」更新覆盖同一 DocumentRecord，不重复建档 | ✅ 稳定 document_id + 版本追加；测试断言 1 条记录 / 2 个版本 |

## 3. 验证

```bash
python3 -m pytest -q        # 153 passed, 2 skipped（全离线）
node --check graph2note/webstatic/app.js
```

**手工浏览器路径（一次性，无需 live 依赖）**：
1. `uvicorn graph2note.webapp:create_app --factory --host 127.0.0.1 --port 8000`，打开 `http://127.0.0.1:8000/`。
2. 首页为空库 → 点「新解析」上传 `test-images/02-digitize-pipeline.jpg` → 解析完成自动进入三栏。
3. 编辑几行 → 看到「已保存 HH:MM:SS」；点「文档库」回首页，见缩略图卡片。
4. 刷新页面（`Cmd+R`）→ 仍停在 `#doc/<id>`；或从列表重开 → **编辑内容保留**。
5. 点「重新解析」→ 确认 → 覆盖为新版（状态栏「第 N 版」）；「删除文档」→ 确认 → 返回空库，本机数据清空。

## 4. 已知问题 / 风险

- **候选版本为最小实现**：FR-022 页级近重复（感知哈希）未实现（属 issue 09/ingest 结论）。MVP 规则=每次新上传独立 `document_id`；`document_id` 稳定者在重新解析时合并为同一记录的版本（留存可查）。同一物理页的**不同**上传不会合并为同一记录——完整 09 集成后接管。
- **Job 内存态**：作业（`/api/jobs/*`）仍为进程内存态，仅解析进度用；文档数据全部落盘（`FileDocumentStore`），页面重开/服务重启后文档库完好。`SessionDocumentStore` 为同一接缝的内存实现（非持久，供 seam 演示/测试）。
- **`doc_id` 与 `document_id` 区分**：`doc_id`=markdown 文件命名（源自原图存储名 `original.*`→`original`），仅作子文件前缀；文档唯一标识为独立 `document_id`。已避免 issue-06 时期「同名上传全合并为一档」的缺陷（不同图片不再因同名 file 串档）。
- **删除非幂等**：重复 DELETE 返回 404（有明确提示）。
- **无密钥/无外部依赖**：全部本机文件读写；网关密钥读取仍走 env/`.gitignore` 的 `.env`。

## 5. 后续（可交给后续 issue）

- 09：基于 ingest 感知哈希的页级近重复 → 把「不同上传的同页」归并到候选版本（复用现有 versions 机制）。
- 11：文档库版本 timing 汇总为速度基线。
- 交叉验证（10）/模板选择器/缺页提示仍是 P1 占位。