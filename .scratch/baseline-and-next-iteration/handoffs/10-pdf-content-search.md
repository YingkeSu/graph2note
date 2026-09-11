# Handoff 10 — 搜索 PDF 内容并跳转命中原页

Branch: `ao/graph2note-16/pdf-content-search` · Issue: `issues/10-pdf-content-search.md` · Status → in-review

## 1. 一句话结论

已解析 PDF 页内容有本地关键词索引，Web 搜索框支持「全部已导入 PDF / 单份 PDF」范围，命中展示
片段并可跳转到对应校对文档与原 PDF 页；新增、编辑、重解析、删除后索引与当前内容一致，索引可
重建且绝不命中已删除内容。首版为关键词检索，不含向量检索，全程无 LLM 调用。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/pdfsearch.py`（新） | `tokenize`（ASCII 词 + CJK 二元组）、`build_index`/`load_index`/`get_index`（内存+磁盘缓存）、`store_fingerprint`（含内容哈希的新鲜度指纹）、`search`（AND 语义、按 PDF 范围、命中片段）；索引持久化到 `<storage>/search/pdf-index.json` |
| `graph2note/webapp.py` | `GET /api/search/pdf?q=&pdf_id=&limit=`、`POST /api/search/pdf/reindex`、`GET /api/pdf`（范围选择器用的轻量列表） |
| `graph2note/pdflib.py` | `PdfJob.summary()`：不含逐页负载的列表/范围视图 |
| `graph2note/webstatic/*` | 文档库搜索栏 + PDF 范围下拉 + 命中卡片（`<mark>` 片段高亮、「打开校对文档」/「查看原 PDF 页」链接）+ 空态/未解析提示 |
| `tests/test_pdf_search.py`（新，6 项） | 中/英/混排检索与完整跳转、单份 vs 全部范围、空态、增删改重解析后的索引一致性、重建/持久化、非 PDF 文档排除 |
| `tests/taxonomy.py` | 登记 `test_pdf_search → webapp` |

## 3. 关键决策

- **只索引有 PDF 来源的页文档**：`pdf_id` + `page_index`（issue 08 provenance）缺一不可；普通单图
  文档不会进入 PDF 搜索（`test_search_ignores_documents_without_pdf_provenance`）。
- **命中页码严格来自 provenance**：`page_index`（0-based 原页序）与可选的 `page_number` 只从页文档
  记录取，不使用文档日期/逻辑编号（AC3）。
- **新鲜度指纹含内容哈希**：store 的 `_now()` 只有秒级精度，同秒内编辑不会改变 `updated_at`；
  仅凭元数据会漏更新。因此指纹 = 每个文档的 `(id, updated_at, 最新 version_id, 当前 markdown 哈希)`，
  任一变化即重建索引——保证编辑/重解析/删除后无陈旧命中（AC4）。
- **一次遍历产出指纹 + 文档**：`_snapshot(store)` 单次扫描同时算出指纹与页文档，命中指纹时复用
  内存/磁盘索引，未命中时直接用同批文档建索引，避免二次读取。
- **AND 语义 + 中英混排**：CJK 走字符二元组（长度 1 的单字保留），ASCII 走小写词；查询是各 token 的
  交集，因此「状态空间」按连续二元组近似短语，「状态空间 filter」要求同时命中（AC2）。
- **命中仍二次校验内容哈希**：`search` 对候选页再取当前 markdown 并比对索引里的 `content_hash`，
  不匹配则跳过；即使索引瞬时陈旧也不会引用旧内容或已删除文档（AC4）。
- **持久化但可重建**：索引写 `<storage>/search/pdf-index.json`，损坏/删除后自动从文档库重建
  （`test_reindex_rebuilds_and_persists`）；`POST /api/search/pdf/reindex` 供显式重建。
- **无向量检索、无 LLM**：纯正则/字典结构，离线测试不触网。

## 4. AC 逐条证据（离线，`tests/test_pdf_search.py`）

| AC | 证据 |
|---|---|
| 1 查询→检索→片段→打开原页与校对文档路径完整；支持单份与全部范围 | `test_search_chinese_english_mixed_with_complete_links`：每个 hit 断言 `review_url` 返回含关键词的 markdown、`source_page_url` 返回 PNG、`pdf_page_url` 返回 200；`test_search_scope_single_pdf_vs_all`：全部命中 2 份 PDF，按 `pdf_id` 过滤后仅 1 条 |
| 2 中文、英文、混排可检索；无命中/无已解析页/仍在导入状态明确 | 混排用同一测试的中/英/「状态空间 filter」三组断言；`test_search_states_no_hit_no_parsed_and_importing`：空库「尚无已解析」、空白页 PDF 范围「尚无已解析页（可能仍在导入）」、未知词「没有匹配」、空 query「请输入关键词」 |
| 3 命中关联来源 PDF、原始页序、内容版本；不误用日期/编号/他页 | hit 含 `pdf_id`/`page_index`/`version_id`；测试回读文档记录断言 `pdf_id`、`page_index` 与 hit 一致；页码仅来自 provenance，未读取任何日期字段 |
| 4 新增/编辑/重解析/删除后一致；可重建；无已删除内容命中 | `test_index_updates_on_edit_reparse_delete`：编辑后旧词 0 命中、新词命中；加新版本后可检索新内容；删除后 `indexed_documents=0` 且旧词 0 命中；`test_reindex_rebuilds_and_persists`：`/reindex` 写入索引文件，删除文件后自动重建 |
| 5 离线 Web/API/索引集成覆盖固定查询、来源跳转与索引更新，无 LLM | 6 项测试全部走 TestClient + 注入 golden router（`RouteARouter` stub），无任何模型调用；来源跳转用 `/api/documents/{id}/source-page` 的真实 PNG 响应 |

### 浏览器验证（AO Browser panel，live）

用离线 router 预置 3 页 PDF 后启动本地 app，在 Browser panel 实际打开库页并执行搜索：
搜索「状态空间」→ 状态行显示「命中 2 条 · 检索范围 3 页」，渲染两条命中（第 1 页 / 第 3 页，均含
「打开校对文档」与「查看原 PDF 页」链接），范围下拉显示「示范扫描.pdf（已入库 3/3 页）」。
（备注：该 panel 的合成点击在本环境不稳定，链接落点为离线测试断言，非重复点击验证。）

## 5. 如何运行

```bash
scripts/run_tests.sh webapp                  # webapp 模块（含搜索测试）
uv run pytest tests/test_pdf_search.py       # 6 passed
uv run pytest -m "webapp or ingest or meta"  # 97 passed
OPENCODE_API_KEY=dummy uv run pytest          # 全量 470 passed
```

## 6. 未尽事项 / 建议

1. **索引性能**：指纹为检测同秒编辑而包含内容哈希，每次搜索会遍历文档取 markdown（本地库规模可接受）；
   若文档量级增大，可在 store 增加单调 revision 或高精度 `updated_at` 后改为纯元数据指纹。
2. **CJK 分词**：当前二元组近似短语匹配，未做同义词/繁简/子词；如需召回率提升可在 issue 11 检索层扩展。
3. **issue 11 消费**：问答检索可直接复用 `pdfsearch.search` 的命中（含 provenance），并把命中页作为
   引用来源；「引用必须来自本次有效来源」可复用 `content_hash` 校验。
4. **UI 交互自动化**：本环境 AO Browser 合成点击不稳，后续若需像素/交互级验收，建议走 issue 04/05
   的 visualqa 命令或修复 panel 输入。

## 7. 相关文件

- 实现：`graph2note/pdfsearch.py`、`graph2note/webapp.py`、`graph2note/pdflib.py`
- 前端：`graph2note/webstatic/{index.html,app.js,style.css}`
- 测试：`tests/test_pdf_search.py`、`tests/taxonomy.py`
- 上游：`handoffs/08-pdf-upload-parse-library.md`、`handoffs/09-pdf-job-recovery-retry.md`
