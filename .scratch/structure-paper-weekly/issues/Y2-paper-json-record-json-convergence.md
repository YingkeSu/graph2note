# Y2 — P1 paper.json 与 P2 record.json.paper 双落点收敛

Status: ready-for-review

来源：`/tmp/review-spw-P2-verdict.md` 残留 R2；`/tmp/review-spw-P3-r2-verdict.md` §8；BOARD P2/P3 行残留「R1 落点收敛（P1 `paper.json` vs P2 `record.json.paper`）」。属 I 轨遗留（Y 轨，可选）。

## What to build

论文 payload 目前有两个落点（`graph2note/store.py`）：

- **P1**（`FileDocumentStore.set_paper_payload`）：sections / fulltext / page_map / source 写 `documents/<id>/paper.json`；`record.json` 只记 `doc_kind` / `paper_source` / `paper_sections`（int 计数）。读取用 `get_paper_payload`。
- **P2**（`set_paper_meta` / `set_paper_references` / `paper_payload`）：meta / references / meta_provenance 写 `record.json` 的 `paper` 槽。读取用 `paper_payload`。

P3 阅读视图（`webapp._paper_view_payload`）同时通过两个 accessor 合并两处，消费者侧已化解（P3-r2 §8：live 9/9 sections 与 P1 payload 逐字段相同、meta/refs 与 P2 一致）。本项为**可选**收敛：决定是否统一到单一落点。

要求：给出裁决并落地——(a) 收敛到 `paper.json`（P2 槽并入 `paper.json`，`paper_payload` 改读同一文件，迁移已存数据 + 向后兼容读）；(b) 保持双落点，但把「两个 accessor + 各自字段集」写进 SPEC §2 作为正式契约，并加不变量测试（两槽不互相覆盖、`_paper_view_payload` 合并正确）。

## Acceptance criteria

- [x] 裁决记录在 Comments（收敛 / 保持 + 理由）：**保持双落点 (b)**，裁决人=维护者，日期 2026-09-15（见 Comments「裁决」条）。
- [x] **N/A**（裁决 (b)，未选收敛路径）：收敛到单文件的迁移/兼容读不在本轮范围。仅保留并钉住既有向后兼容读（`get_paper_payload` 在 `paper.json` 缺失时回退旧式 `record.json.paper`），由 `test_legacy_record_slot_payload_is_still_readable` 覆盖。
- [x] 若 (b) 契约化：SPEC §2 新增「落点与 accessor 契约（双落点）」——双落点字段表（P1 结构槽 / P2 元数据槽，含物理位置、字段集、唯一写入方、唯一读取 accessor）+ accessor 约定（返回值/回退/None 语义、`record.json` 轻量镜像不得当 payload）+ 不变量 I1–I5；新增不变量测试 `tests/test_papers_meta_dualslot.py`（14 例，覆盖 I1 写 meta 不动 sections、I2 写 sections 不动 meta、I3 P2 内部互不覆盖、I4 `_paper_view_payload` 合并逐字段正确 + P2 槽无法夹带 sections、I5 持久化重载一致 + 旧槽兼容读）。
- [x] 两方案均须：P1/P2/P3 全链路 live 集成不回归——P3-r2 live 脚本改指向本 worktree 重跑 **32/32 PASS**（零模型调用，未读 `.env`）；另加 Y2 专项双落点 live 探针 **17/17 PASS**。**零运行时代码改动**：`webapp.py`/`store.py` diff 为空（严格优于「只追加」）。
- [x] 全量 `pytest -p no:warnings` **1238 passed**（EXIT=0；分支点 main `5ddc66a` 实测基线 1224，新增 14 例）；node 套件绿（由全量 pytest 内的 node 包装用例覆盖；`.mjs` 逐个直跑除 `graph_interaction.mjs` 需 stdin payload 外均 OK——该脚本由 `test_graph_interaction.py` 喂 payload 运行，非回归）。
- [x] mutation 有牙：A 让 durable `paper_payload` 返回 `{}` → 新测试 **7 红**；B 让 durable `get_paper_payload` 返回 `{}` → 新测试 **7 红**（两者均已实测并回退）。

## Blocked by

无。属重构/契约项，优先级低于功能性 issue；若排期紧张可只做 (b) 的文档 + 不变量测试。

## 领地

- 独占：`graph2note/store.py`（paper 槽方法）、`graph2note/webapp.py`（`_paper_view_payload` 只追加调整）、`SPEC.md` §2、`tests/test_papers_meta*.py`、`tests/test_papers_view.py`、`tests/test_papers_ingest*.py`。
- 禁止：解析算法 `papers/metadata.py`/`references.py`、渲染/抽取代码、I 轨其他 issue 文件。

## Comments

- P3-r2 §8 原文：「P2-R2 落点分叉（P1 `paper.json` vs P2 `record.json.paper`）在消费者侧经公共缝读取消除对 P3 的影响；是否收敛由 P1/P2 维护者决定。」
- P2 verdict R2：「P2 在 `papers/metadata.py`/`references.py` 自建 `PaperMeta`/`PaperReference`，P1 在 `papers/model.py` 另有一套 SPEC §2 同名契约类」，一并决定是否统一契约类（本项至少记录处置）。

### 裁决（维护者，2026-09-15）：保持双落点 (b) + 契约化

- **结论**：**不收敛**，保持 P1 `paper.json` 与 P2 `record.json.paper` 两个落点；把「两个 accessor + 各自字段集 + 不变量」写进 SPEC §2 作为正式契约，并加不变量测试。
- **理由**：P3 阅读视图已在消费侧经两个 accessor 合并化解分叉（P3-r2 §8：live 9/9 sections 与 P1 payload 逐字段相同、meta/refs 与 P2 一致）；收敛到单落点需要迁移已存数据 + 向后兼容读，**重构风险大于收益**。
- **决策人**：维护者；**日期**：2026-09-15。落地形态见 SPEC §2「落点与 accessor 契约（双落点）」；测试 `tests/test_papers_meta_dualslot.py`。
- **重复契约类处置（P2 verdict R2）**：**保留两套，不统一**。`papers/model.py`（P1）与 `papers/metadata.py`/`references.py`（P2）的同名 `PaperMeta`/`PaperReference` 字段集与类型**逐字段相同**（`extra="forbid"`）。理由：落点契约以 **dict** 为准（store accessor 层），两侧互不 import；P2 的两个类承担本模块的校验/归一化职责（如 `metadata.PaperMeta` 的 DOI 归一化），`model.py` 的类只作 `PaperPayload` 的占位 schema；统一需跨模块重构（`papers/metadata.py`/`references.py` 在本项领地之外），收益仅为去重，风险大于收益。防漂移：`test_duplicate_contract_classes_share_field_sets` 钉住字段集与 JSON schema 一致。

### 交付记录（2026-09-15，dev/Y2-dualslot-contract）

分支 `dev/Y2-dualslot-contract`（基于 main `5ddc66a`，未 push）。**零运行时代码改动**（`store.py`/`webapp.py` diff 为空）。

改动：
- `.scratch/structure-paper-weekly/SPEC.md` §2（+28 行，append-only）：新增「落点与 accessor 契约（双落点；2026-09-15 维护者裁决 (b)）」——裁决块（结论/理由/决策人/日期）、双落点字段表、accessor 语义（`get_paper_payload` 的 None/回退/`{}` 语义与旧槽兼容读；`paper_payload` 的 None/`{}` 语义；`record.json` 镜像字段 `doc_kind`/`paper_source`/`paper_sections` 不是 payload）、`SessionDocumentStore` 单槽说明、不变量 I1–I5、重复契约类处置。
- `tests/test_papers_meta_dualslot.py`（新，14 例，全离线零网络零 LLM）：I1 durable `paper.json` 逐字节不变 + session store 结构字段不变；I2 `set_paper_payload`/`save_paper_document`/`update_paper_payload` 均不动 P2 槽、且 P1 不创建缺失的 P2 槽；I3 P2 内部三次写入互不覆盖；槽字段集边界（P1-only 键不出现在 P2 accessor）；I4 `GET /api/papers/{id}/view` 与显式期望字典**逐字段**相等、P2 优先于 P1 占位、P2 槽夹带 `sections` 不生效、两槽皆无时退空默认；I5 重开 store 后两 accessor + 视图不变；旧式 `record.json.paper` 兼容读；重复契约类字段集/schema 一致。
- `tests/taxonomy.py`（+1 行）：登记 `test_papers_meta_dualslot` → `store`。

证据：
- 全量 `/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest -p no:warnings` → **1238 passed**，EXIT=0（分支点 `5ddc66a` 实测基线 1224；本项 +14 例，数点法精确对上）。
- live 全链路：`/tmp/spw-Y2-live.py`（P3-r2 脚本改指本 worktree、移除 `.env` 加载）→ **32/32 PASS**；Y2 专项探针 `/tmp/spw-Y2-dualslot-live.py`（真实 HTTP 导入 → P2 写入 → on-disk 检查）→ **17/17 PASS**。两者均 `router_factory` 抛错守卫 = 零模型调用，密钥未打印未导出。
- mutation 有牙（实测后已回退）：A durable `paper_payload` → `{}` ⇒ 7 红；B durable `get_paper_payload` → `{}` ⇒ 7 红。
- 详细证据见 `/tmp/spw-Y2-done-report.md`。

截图/演示：无（契约 + 测试项，无 UI 变更）。
