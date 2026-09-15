# P2 — 论文元数据与参考文献识别

Status: ready

来源：维护者 2026-09-14 指令「针对论文识别读取做全线优化」；共享契约 [SPEC.md §2](../SPEC.md)。

## What to build

`graph2note/papers/` 内的元数据与参考文献识别模块：从论文全文文本（首页 + 参考文献区）确定性解析出 `PaperMeta`（标题/作者/年份/venue/DOI/摘要/关键词）与 `references: list[PaperReference]`；库内引用关联——参考文献条目与库中已有论文按 DOI/标题规范化匹配时回填 `resolved_document_id`。LLM 可作为可选增强（提议 + schema 校验 + 人可改），但无 key 环境全链路确定性可用；默认不访问外部服务（CrossRef 类在线解析如实现，必须可选、可关、测试离线）。

## Acceptance criteria

- [ ] 确定性解析：自建 fixture（≥3 种典型排版的首页文本：单栏期刊、双栏会议、arXiv 预印本）解析出正确 title/authors/year/venue/doi/abstract；解析器为纯函数，离线可测、可回放。
- [ ] 参考文献区定位与条目切分：fixture 的「References / Bibliography / 参考文献」区被正确定位，条目逐条切分（编号 [1] / 作者-年份 两种风格），每条解析出 raw + 尽可能多的 title/authors/year/doi；切分错误的 fixture 变体（跨栏断行、缺编号）有可解释行为（保守合并且 provenance 标注，不静默造条目）。
- [ ] 库内关联：构造库内已存在同 DOI / 同规范化标题论文的 fixture，断言 `resolved_document_id` 正确回填；无匹配时为空，不假匹配（标题规范化：大小写/标点/空白折叠）。
- [ ] 与 P1 的集成点通过契约解耦：输入为「全文文本 + 首页文本 + 参考文献区文本」的纯数据结构（自建 fixture），**不 import P1 未合并代码**；产出落库方式（meta.json / document meta 槽位）与 SPEC §2 一致，webapp 只追加 `/api/papers/*` 段内的元数据查询/人工修正端点。
- [ ] LLM 增强可选：无 key 时全部测试绿；有 key 路径走可注入 gateway，CI 不触网；LLM 提议必须过 schema 校验，不绕过确定性结果。
- [ ] 全部测试离线；新增测试文件独立命名（如 `tests/test_papers_meta.py`）；全量 pytest 绿。

## Blocked by

无（通过 SPEC §2 契约与 P1 并行；集成验证由 reviewer 在 P1 合并后执行）。

## 领地

- 独占：`graph2note/papers/metadata.py`、`references.py`、`citegraph.py`（命名可调）、`tests/test_papers_meta*.py`。
- 只追加：`graph2note/webapp.py`（`/api/papers/*` 段内元数据/参考文献端点，与 P1 的段相邻但独立函数，追加不改动 P1 已合并行）、`graph2note/store.py`（确需时只追加）。
- 禁止：`ir.py`、`diagram*`、`digest.py`、`dashboard.js`、`index.html`、`router.js`、`upload.js`、`papers/pipeline.py/textlayer.py/structure.py`（P1 领地）。

## Comments

### 交付记录（worker P2，2026-09-15）

Status: **ready-for-review**。分支 `dev/P2-paper-meta`（基线 main `3c64d60`），handoff：[`handoffs/P2-paper-metadata-references.md`](../handoffs/P2-paper-metadata-references.md)。

- 新包 `graph2note/papers/`：`metadata.py`（首页确定性解析）/ `references.py`（参考文献定位+切分）/ `citegraph.py`（库内关联）/ `enhance.py`（可选 LLM，schema 校验）。
- 只追加：`webapp.py`（`/api/papers/*` 段）、`store.py`（`paper` 槽位新方法）、`tests/taxonomy.py`（登记）。未改任何既有行。
- 测试：全量 `pytest -p no:warnings` 1087 passed；P2 新测试 40 passed；`tests/*.mjs` 独立用例全绿（`graph_interaction.mjs` 由其 Python 驱动用例覆盖）。
- 边界：全程离线；live LLM 通道未调用（`live: true` 才启用，可注入 planner）。与 P1 通过 SPEC §2 契约解耦，未 import P1 代码。
