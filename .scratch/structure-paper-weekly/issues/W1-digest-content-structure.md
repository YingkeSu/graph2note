# W1 — 周报内容结构与材料策略优化

Status: ready

来源：维护者 2026-09-14 指令「优化周报模块」；共享契约 [SPEC.md §3](../SPEC.md)。现状：`digest.py`（A2 交付）单次 text LLM 调用生成整篇 Markdown，无分节结构、统计信息混入 LLM 输出、来源追溯只有整篇级 source ids。

## What to build

周报生成升级为「确定性骨架 + 分节填充」：按 SPEC §3 的四节结构（本周概览 / 主题脉络 / 重点文档摘录 / 待整理与连续体进展）生成；统计性内容（文档数、新增数、解析成功率、inbox 积压数等）**确定性计算不调 LLM**；LLM 只填充归纳性段落且按节进行（可选单次调用输出分节 JSON，schema 校验）；每节携带 `source_document_ids` 来源追溯；指纹缓存机制延续并升级——材料不变时整报零 LLM 调用，单节材料不变时该节命中缓存（节级指纹为加分项，整报级必须保持）。meta.json 写入 `sections: [{key, title, source_document_ids}]` 供 W2 消费。

## Acceptance criteria

- [ ] 生成的周报 Markdown 含四节确定性骨架（节标题/顺序固定）；「本周概览」节中的统计数字由纯函数计算，离线测试断言与构造库状态一致（不经 LLM）。
- [ ] 每节 `source_document_ids` 与实际引用一致；meta.json 含 `sections` 结构且重载后仍成立；旧格式 meta（无 sections）读取不炸（向后兼容）。
- [ ] 指纹缓存延续：同指纹重复请求零 LLM 调用（沿用现有断言方式）；`force=True` 才重新生成。
- [ ] 材料预算策略可解释：超 `MAX_DOCS` 时的取舍规则（如按有效时间优先 + 各主题保底配额）为确定性纯函数并有测试；预算/阈值集中在模块常量区。
- [ ] LLM 通道与 purpose session 隔离延续；无 key 环境 golden planner 注入测试全绿，CI 不触网。
- [ ] 新增/修改测试覆盖四节结构、统计纯函数、缓存命中、预算取舍；全量 pytest 绿。

## Blocked by

无。

## 领地

- 独占：`graph2note/digest.py`、`tests/test_digest*.py`。
- 只追加：`graph2note/webapp.py`（`/api/digests/*` 既有段内，确需时）、`graph2note/telemetry.py`（确需时只追加）。
- 禁止：`dashboard.js`、`index.html`（W2 领地）、`ir.py`、`diagram*`、`papers/*`。

## Comments

（待 worker 填写交付记录）
