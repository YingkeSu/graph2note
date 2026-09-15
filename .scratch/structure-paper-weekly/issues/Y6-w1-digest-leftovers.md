# Y6 — W1 周报遗留 R1–R5 汇总

Status: ready

来源：`/tmp/spw-W1-done-report.md` 遗留节；`handoffs/W1-digest-content-structure.md` §6；BOARD W1 行残留 R7/R8。属 I 轨遗留（Y 轨，聚合项）。

## What to build

聚合 W1 reviewer/作者记录的 5 条遗留（每条独立验收，可分批实现）：

- **R1 连续体「待确认对」在生产路径基本为 0**：digest 收到的 records 不带 IR；库 >200 篇时按设计只算显著层。修它需动 `webapp.py`/`store.py`（越 W1 领地）。
- **R2 `stats.inbox_*` 与材料分区口径不同**：`stats.inbox_*` 是 Inbox 原样投影（含「仅缺标签」），材料分区以「无标签才算待整理」；W2 并排展示时需知。
- **R3 meta 变大（KB 级/条）**：无上限/裁剪策略说明。
- **R4 长材料下模型 JSON 稳定性未压测**（有 fallback 兜底）。
- **R5 `llm_calls=0` 时 `elapsed=0.0`**：语义与 A2 的「1 次调用总耗时」不同。

（同一批还有 W1 verdict 残留 **R7** `GENERATOR_VERSION` 进整报指纹无回归测试（功能正确、mutation C 仍绿）与 **R8** 裁剪时 `stats.document_count`（范围内总数）与 `meta.document_count`（选入数）同名异义、概览 source ids 含被裁剪文档——若认为属同一批，在 Comments 追加并补验收。）

## Acceptance criteria

按条拆分，每条独立关闭：

- [ ] R1：明确「连续体待确认对」在生产路径的期望口径（0 是否可接受，还是须注入 IR 摘要），并落地其一：要么在 `webapp.py`/`store.py` 侧向 digest 提供 IR 摘要，要么在报告/文档中标注该统计在生产环境不适用；附测试或明确说明无法测的原因。
- [ ] R2：统一或显式区分两口径：meta/stats 字段命名区分（如 `inbox_backlog` vs `pending_untagged`）并加断言锁定；W2 前端展示不歧义。
- [ ] R3：给出 meta 体积上限/裁剪策略或量化说明（记录实测体积与阈值决策）。
- [ ] R4：对长材料（≥ `MAX_DOCS`）做模型 JSON 稳定性压测或离线回退测试，记录坏 JSON/纯散文回退仍产出四节的证据。
- [ ] R5：`llm_calls=0`（缓存命中）时 `elapsed` 语义澄清：改字段名/加 `cached` 标注/文档说明，二者取一并加断言。
- [ ] R7（可选并入）：`GENERATOR_VERSION` 进整报指纹补回归测试（mutation：删除版本入指纹应红）。
- [ ] R8（可选并入）：`stats.document_count` 与 `meta.document_count` 同名异义，改名或加断言区分。
- [ ] 每条的落地/未落地逐条记录（不必一次全做；本 issue 可分批，每条独立关闭）。
- [ ] 不改 W2 前端行为契约：若 R2/R8 改字段名，需同步 W2 消费端与 node 套件。
- [ ] 全量 `pytest -p no:warnings` 绿。

## Blocked by

无（R1 需跨 `webapp.py`/`store.py` 领地，排期时先确认）。

## 领地

- 独占：`graph2note/digest.py`、`tests/test_digest_structure.py`、`tests/test_digest_budget.py`、`tests/test_weekly_digest.py`。
- 只追加：`graph2note/store.py`/`graph2note/webapp.py`（仅 R1 需要，追加只读/聚合接口）、`graph2note/webstatic/js/views/dashboard.js`（仅 R2/R8 字段名同步，最小追加）。
- 禁止：破坏 W1 已合并的四节契约（SPEC §3）、`papers/*`、抽取/渲染代码。

## Comments

- W1 done-report 遗留原文见上「What to build」；W1 verdict 残留 R7/R8 记为「功能正确、mutation C 仍绿」与「同名异义、概览 source ids 含被裁剪文档」。
- W2 已合并并消费 `meta.sections`/`stats`；改字段名须回归 `tests/digest_view_dom.mjs`（node 套件）与 `tests/test_digest_view.py`。
