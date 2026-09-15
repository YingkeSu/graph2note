# Y1 — PATCH /api/papers/{id}/metadata 与 PUT 同为整体替换，静默清字段

Status: ready

来源：`/tmp/review-spw-P2-verdict.md` 残留 R1；`/tmp/review-spw-P3-r2-verdict.md` §8；BOARD P2 行残留「R1 PATCH `/metadata` 与 PUT 同为整体替换」。属 I 轨遗留（Y 轨）。

## What to build

`graph2note/webapp.py` 的 `/api/papers/{document_id}/metadata` 把 **PUT 与 PATCH 挂在同一个 handler** `papers_update_metadata` 上：`raw = payload.get("meta", payload)` → `PaperMeta.model_validate(raw)` → `store.set_paper_meta(document_id, meta.model_dump(), ...)`。PATCH 传部分 body 时未提供的字段取默认空值、验证通过后**整体覆盖**。

实测（P2 verdict R1）：`PATCH {"meta":{"title":"New Title"}}` 返回 200 + `source:"manual"`，但 authors/year/doi 被清空。SPEC §2 未定义 PATCH 语义，验收项亦未覆盖；P3 阅读视图只读、未消费该端点（P3-r2 §8），故非阻塞但为静默丢字段陷阱。

要求：二选一并落地——(a) PATCH 改为**部分合并**语义（先把 body 合并进既有 meta 再验证，仅本次提供的字段 provenance 标 manual），PUT 保持整体替换；(b) 删 PATCH 路由，仅保留 PUT，并在 SPEC §2 注明。

## Acceptance criteria

- [ ] 若选 (a)：`PATCH {"meta":{"title":"…"}}` 只改 title，authors/year/venue/doi/abstract/keywords 保留既有值，返回体逐字段断言；仅 title 的 provenance 标 `manual/high`，其余不变。
- [ ] 若选 (b)：PATCH 路由从 `app.routes` 移除、PUT 行为不变；全仓无 PATCH 消费者（含前端）并有断言。
- [ ] 两方案均须：未知字段仍 422（`PaperMeta` `extra="forbid"`）；非法 year 等仍 422；PUT 整体替换语义有显式测试（与 PATCH 区分）。
- [ ] `GET` 端点与 `_paper_payload` 形状不变；持久化重载后语义一致（新建 store 重读）。
- [ ] `webapp.py` 只追加/最小改动（不改 P1/P3 已合并行）；若更新 SPEC §2 定义 PATCH/PUT 语义，一并提交。
- [ ] mutation 有牙：选 (a) 时把 PATCH 改回整体替换、选 (b) 时重新挂上 PATCH，新测试均变红。
- [ ] 全量 `pytest -p no:warnings` 绿。

## Blocked by

无。若决定删 PATCH，需确认无外部消费者（仓库内已确认 P3 只读）。

## 领地

- 独占：`graph2note/webapp.py` 的 `/api/papers/{id}/metadata` 处理器段、`tests/test_papers_meta_api.py`。
- 只追加：`graph2note/store.py`（若需 `paper_payload` 合并辅助，只追加方法）。
- 禁止：`graph2note/papers/*` 解析逻辑、`/api/documents/{id}/metadata`（既有 PUT/PATCH 别名，非本 issue）、I 轨其他文件。

## Comments

- P2 verdict R1 原文：「`PATCH /api/papers/{id}/metadata` 与 PUT 共用同一处理器，语义是**整体替换**。实测 `PATCH {"meta":{"title":"New Title"}}` 会把 authors/year/doi 清空（返回 200 + `source:"manual"`）。... 建议改为与既有槽位合并或仅保留 PUT。」
- 注意 `webapp.py:1491-1492` 的 `/api/documents/{document_id}/metadata` 也把 PUT/PATCH 挂在同一 handler；那是既有通用文档行为、不属本 issue，若需统一语义另开 issue。
