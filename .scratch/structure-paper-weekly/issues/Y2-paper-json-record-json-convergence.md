# Y2 — P1 paper.json 与 P2 record.json.paper 双落点收敛

Status: ready

来源：`/tmp/review-spw-P2-verdict.md` 残留 R2；`/tmp/review-spw-P3-r2-verdict.md` §8；BOARD P2/P3 行残留「R1 落点收敛（P1 `paper.json` vs P2 `record.json.paper`）」。属 I 轨遗留（Y 轨，可选）。

## What to build

论文 payload 目前有两个落点（`graph2note/store.py`）：

- **P1**（`FileDocumentStore.set_paper_payload`）：sections / fulltext / page_map / source 写 `documents/<id>/paper.json`；`record.json` 只记 `doc_kind` / `paper_source` / `paper_sections`（int 计数）。读取用 `get_paper_payload`。
- **P2**（`set_paper_meta` / `set_paper_references` / `paper_payload`）：meta / references / meta_provenance 写 `record.json` 的 `paper` 槽。读取用 `paper_payload`。

P3 阅读视图（`webapp._paper_view_payload`）同时通过两个 accessor 合并两处，消费者侧已化解（P3-r2 §8：live 9/9 sections 与 P1 payload 逐字段相同、meta/refs 与 P2 一致）。本项为**可选**收敛：决定是否统一到单一落点。

要求：给出裁决并落地——(a) 收敛到 `paper.json`（P2 槽并入 `paper.json`，`paper_payload` 改读同一文件，迁移已存数据 + 向后兼容读）；(b) 保持双落点，但把「两个 accessor + 各自字段集」写进 SPEC §2 作为正式契约，并加不变量测试（两槽不互相覆盖、`_paper_view_payload` 合并正确）。

## Acceptance criteria

- [ ] 裁决记录在 Comments（收敛 / 保持 + 理由）。
- [ ] 若 (a) 收敛：`set_paper_meta`/`set_paper_references`/`paper_payload` 与 `get_paper_payload` 落同一文件；旧数据（已有 `record.json.paper` 槽）读取兼容；迁移测试覆盖「旧槽有数据、新读路径正确」。
- [ ] 若 (b) 契约化：SPEC §2 新增双落点字段表 + accessor 约定；新增不变量测试（写 meta 不动 sections、写 sections 不动 meta、P3 合并 payload 逐字段正确、持久化重载一致）。
- [ ] 两方案均须：P1/P2/P3 全链路 live 集成不回归（沿用 P3-r2 的 32/32 live 脚本口径或等价）；`webapp.py` 只追加。
- [ ] 全量 `pytest -p no:warnings` 绿；node 套件（`paper_view.mjs`、`library_cards.mjs` 等）绿。
- [ ] mutation 有牙：破坏其中一个落点的读取（如让 `paper_payload` 返回空）时新测试变红。

## Blocked by

无。属重构/契约项，优先级低于功能性 issue；若排期紧张可只做 (b) 的文档 + 不变量测试。

## 领地

- 独占：`graph2note/store.py`（paper 槽方法）、`graph2note/webapp.py`（`_paper_view_payload` 只追加调整）、`SPEC.md` §2、`tests/test_papers_meta*.py`、`tests/test_papers_view.py`、`tests/test_papers_ingest*.py`。
- 禁止：解析算法 `papers/metadata.py`/`references.py`、渲染/抽取代码、I 轨其他 issue 文件。

## Comments

- P3-r2 §8 原文：「P2-R2 落点分叉（P1 `paper.json` vs P2 `record.json.paper`）在消费者侧经公共缝读取消除对 P3 的影响；是否收敛由 P1/P2 维护者决定。」
- P2 verdict R2：「P2 在 `papers/metadata.py`/`references.py` 自建 `PaperMeta`/`PaperReference`，P1 在 `papers/model.py` 另有一套 SPEC §2 同名契约类」，一并决定是否统一契约类（本项至少记录处置）。
