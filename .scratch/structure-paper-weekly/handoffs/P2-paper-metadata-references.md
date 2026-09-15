# P2 — 论文元数据与参考文献识别（handoff）

Status: **ready-for-review**
分支：`dev/P2-paper-meta`（基线：本地 main `3c64d60`）
作者：SPW I 轨 worker P2
日期：2026-09-15

## 结论一句话

`graph2note/papers/` 内新增确定性的 `PaperMeta` + `list[PaperReference]` 识别：三种典型首页排版（单栏期刊 / 双栏会议 / arXiv 预印本）逐字段解析、参考文献区定位与条目切分（编号 / 作者-年份，含保守合并与 provenance）、库内 DOI/规范化标题关联回填 `resolved_document_id`、可选且 schema 校验的 LLM 增强（可注入、无 key 全链可用）。**全程离线可测**；live LLM 通道未调用（见「离线/live 边界」）。与 P1 完全通过 SPEC §2 契约解耦，**未 import 任何 P1 未合并代码**。

## 提交（每逻辑单元一个）

| commit | 说明 |
|---|---|
| `a343fd8` | `feat(papers): deterministic paper metadata & reference parsing` |
| `2968e57` | `feat(papers): in-library reference resolution and citation graph` |
| `c0ca7ed` | `feat(papers): optional schema-validated LLM metadata enhancement` |
| `a5940a5` | `feat(store): append paper metadata/reference slots` |
| `1cedf64` | `feat(webapp): append /api/papers/* metadata & references routes` |
| `48527d4` | `test(papers): offline unit + API/store contracts` |

`git diff --stat main...HEAD`：新增 11 文件（4 个实现模块 + 1 fixtures 目录 + 5 fixture + 2 测试），既有文件仅追加：`webapp.py` +166、`store.py` +184、`tests/taxonomy.py` +3，**0 行删除**。

## 改动清单

### 新包 `graph2note/papers/`
- `__init__.py`：包文档（**注意**：P1 也会建同名包，见「合并注意」）。
- `metadata.py`：
  - `PaperMeta`（SPEC §2 全字段，`extra="forbid"`；DOI 经 `field_validator` 规范化）、`FieldProvenance`、`PaperText`（契约纯输入：full/front/references text）、`PaperMetaResult`。
  - `parse_paper_meta(front_text, *, full_text, source)` + `split_front_text`；`normalize_title` / `normalize_doi`（citegraph 复用同一实现）。
  - 段落化首页：先剥离页眉（卷期/版权/arXiv id/DOI/venue），再切标题 / 作者段；摘要、关键词、DOI、年份、venue 各自带证据与置信度。
- `references.py`：
  - `PaperReference`（SPEC §2 全字段）、`ReferenceEntry`（内部富模型：style/fragments/notes + `.reference()` 投影）、`ReferenceProvenance`、`ReferenceSection`、`ReferenceParse`、`PaperDocument`。
  - `locate_references_section`（References/Bibliography/Works Cited/参考文献，取**最后一个**标题，遇 appendix/致谢截断）、`split_reference_entries`、`parse_reference_entry`、`parse_references`、`extract_references`、`parse_paper_text`（一次跑完 meta+refs）。
- `citegraph.py`：`LibraryEntry` / `CitationIndex`（`build_index` 对重复 key 判为 ambiguous 并剔除，**不假匹配**）、`resolve_references`、`build_citation_graph`、`library_entries_from_documents`（从 store 记录读 `paper.meta.doi`）。
- `enhance.py`：`MetaProposal`（`extra="forbid"` + 年份范围 + 列表/文本清理）、`validate_meta_proposal`、`apply_meta_proposal`（**只填空字段，绝不覆盖确定性结果**）、`enhance_meta`（planner 缺失/异常/非法 JSON 一律降级为确定性结果 + note）、`live_planner`（`ir_text` 通道、gateway seam）。

### 只追加共享文件
- `graph2note/store.py`：新增方法（`SessionDocumentStore` 与 `FileDocumentStore` 各一份）——`paper_payload` / `set_paper_meta` / `set_paper_references` / `set_paper_reference_resolution` / `list_paper_entries`。未改任何既有方法或签名。
- `graph2note/webapp.py`：在 `create_app` 内新增独立 `/api/papers/*` 段（`parse-metadata`、`/{id}/metadata` GET/PUT/PATCH、`/{id}/references` GET、`/{id}/references/resolve` POST、`/{id}/references/{index}` PATCH、`/{id}/metadata/enhance` POST）。未改 P1 或任何既有行。
- `tests/taxonomy.py`：追加 2 行登记（`test_papers_meta`→workspace、`test_papers_meta_api`→webapp + integration）。

## 契约对齐决策（供 reviewer / P1 / P3）

1. **落库形状（append-only）**：论文数据存于 `record["paper"]`：
   ```
   {"paper": {"meta": {…PaperMeta…},
              "meta_provenance": {field: {source, confidence, evidence}},
              "references": [ PaperReference, … ],
              "references_provenance": [ {index, style, fragments, notes}, … ],
              "source": "text-layer"|"vlm"|"manual",
              "notes": [ … ],
              "parse": {…可选…}},
    "doc_kind": "paper"}
   ```
   `doc_kind` 用 `rec.get("doc_kind") or "paper"` 写入，不覆盖 P1 已有值。P1 若改走 `meta.json` 文件，P2 的读路径只需把 `paper_payload` 指过去（当前实现只读 record 槽位，已在 API 层归一化输出全字段）。
2. **provenance 不进本体**：SPEC 明确 `PaperMeta` 每个字段的来源放 provenance；`PaperReference` 同构处理，富信息放 `ReferenceProvenance`，契约投影仍是纯 `PaperReference`。
3. **保守切分语义**：编号缺失且无法可靠识别条目起点时**合并**并在 provenance 打 `merged-incomplete` / `merged-continuation` / `merged-no-separator`；跨栏断行 `dehyphenated`。绝不静默造条目。
4. **LLM 优先级**：确定性结果永远优先；proposal 只能补空字段；非法 proposal（多键/类型/年份越界）整体丢弃；无 planner 或传输失败返回「确定性结果 + note」，不抛错。
5. **live 需显式开关**：`POST …/metadata/enhance` 仅在 body 带 `live: true` 时才构造 `live_planner()`；默认离线。Web 层通过 `app.state.paper_meta_planner` 注入离线 stub（未改 `create_app` 签名）。

## 验收对照

- [x] 确定性解析：3 种排版 fixture（单栏期刊 / 双栏会议 / arXiv）逐字段断言；纯函数、`model_dump` 可重放（`test_meta_parse_is_pure_and_replayable`）。
- [x] 参考文献区定位 + 条目切分：编号 / 作者-年份两种风格；跨栏断行、缺编号变体有 `merged-*` / `dehyphenated` provenance，保守合并不造条目。
- [x] 库内关联：DOI 优先、规范化标题回填 `resolved_document_id`；重复 key 判 ambiguous 不匹配；无匹配为空。
- [x] 与 P1 解耦：输入为 `PaperText`（full/front/references text）纯数据结构，**不 import P1**；落库形状与 SPEC §2 一致（`doc_kind:"paper"` + `paper` 槽位）；webapp 只追加 `/api/papers/*`。
- [x] LLM 增强可选：无 key 全测试绿；`planner` 可注入；proposal 过 schema；离线端点默认不触网。
- [x] 全部测试离线；新增独立命名测试文件；taxonomy 已登记。

## 测试证据（可复跑）

```
# 全量（本 worktree，主仓 .venv Python 3.13）
/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest -p no:warnings
# 1087 passed in 132.92s

# P2 新测试
… -m pytest -p no:warnings tests/test_papers_meta.py tests/test_papers_meta_api.py
# 40 passed

# node 契约（11 个独立 .mjs 全绿；graph_interaction.mjs 需 stdin payload，由其 Python 驱动测试 tests/test_graph_interaction.py 覆盖并已随全量 pytest 通过）
for f in tests/*.mjs; do node "$f"; done
```

覆盖点：三排版字段级断言；空首页 `none` 且不臆造；TOC/中文/appendix 定位；编号/作者-年份/缺编号/跨栏断行切分；年份缺失保守合并；无法解析条目的显式 note；DOI 优先、标题规范化、ambiguous 不匹配、citation graph 去重排序；proposal 覆盖拒绝/补空/provenance 标 `vlm`/非法拒绝；API parse/get/put/resolve/patch/enhance + 持久化重载 + 404/422。

## 离线 / live 边界（诚实标注）

- **全部测试离线**：未发生任何外部网络调用；LLM 路径用注入 stub，`live` 只走「显式开关」分支且测试不触发。
- **live LLM 未调用**：本环境未对 `live_planner` 做真实 gateway 调用；`enhance` 的真实模型质量未验证，仅证明「契约 + 降级路径正确」。如需 live 验证，用 `POST /api/papers/{id}/metadata/enhance {"live": true}`（通道 `ir_text`），本报告不记录任何 key/产物。主仓 `.env` 是否存在 key 未读取、未打印。
- 默认路径（无 key / 无 planner）确定性全链可用。

## 诚实限制

1. **参考文献字段抽取是 best-effort**：`authors` 对「姓名-首字母」两种主流风格可靠，对混排/机构作者的边界情况可能留空并标 `authors-unparsed`；`venue` 不在 `PaperReference` 契约内，故未解析。
2. **首页解析面向行式文本**：真实双栏 PDF 的文本层顺序依赖 P1 的抽取质量；P2 只对行序负责。
3. **未做 CrossRef 类在线补全**：SPEC 允许但非必需；本轮不实现，避免任何默认外网依赖（若后续实现须可选、可关、离线可测）。
4. **`pyproject.toml` 未改**：新包 `graph2note.papers` 未加入 `[tool.setuptools] packages`（该文件非本任务领地且 P1 也会改，避免并行冲突）。合入时由 P1 或集成者补 `"graph2note.papers"` 一行即可；测试与源码运行不依赖该条目。
5. **live 端点未加前端入口**：P3 消费只读展示时再接线；本轮只交付 API。

## 合并注意（P1 → P2）

- `graph2note/papers/__init__.py`：P1 与我方都会新建/写入该文件 → 预期冲突；保留 P1 内容并按需并入本包文档即可（我方 `__init__.py` 仅一句文档，无代码）。
- `pyproject.toml`：见限制 4。
- `tests/taxonomy.py`：我方已追加 2 行，P1 追加其行；均为相邻追加，冲突可机械合并。
- `webapp.py` / `store.py`：纯追加、无删除行；按合并序 P1→P2 resolve 时保留双方段落即可。
- P3 集成：直接读 `GET /api/papers/{id}/metadata`（返回归一化全字段 meta + references + provenance）；库内关联可调 `POST …/references/resolve`。

## 领地偏差

无。除独占的 `graph2note/papers/{metadata,references,citegraph,enhance}.py` 与 `tests/test_papers_meta*.py`、`tests/fixtures/papers/` 外，仅在 `webapp.py`（`/api/papers/*` 独立段）、`store.py`（新方法）、`tests/taxonomy.py`（登记）做纯追加。未触碰 `.scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md`，未改 `ir.py`/`diagram*`/`digest.py`/webstatic 等禁区。
