# S1：IR 块级 diff 引擎（DiffReport 纯函数）

Status: ready-for-agent
Labels: track-semantic, priority-high

## What to build

覆盖 usable-product-iteration 草案 §2.3。实现 Document IR 层的块级语义对比引擎，为版本间演进分析提供确定性内核。纯函数、零模型调用、零 IO（输入是两份 IR，输出是结构化报告）。

输入：同一文档两个版本的 `ir.json`（store 每版本已完整落盘，无需重新解析）。输出 `DiffReport`：

- **块级操作序列**：每对版本间的块变更 = `{op: added | removed | modified | moved | unchanged, block_ref_a?, block_ref_b?, block_type}`；块类型沿 Document IR 既有类型（标题/段落/公式/图表等）。
- **匹配算法**：先按块类型分组，组内做相似度匹配（文本块用规范化 token 重叠率等确定性度量；公式/图表用各自结构字段），相似度 ≥ 阈值判 `modified`（携带相似度分），低于阈值分别判 `removed`+`added`；位置变化但内容匹配判 `moved`。阈值常量显式定义、可测试。
- **汇总统计**：按类型计数、变更密度（变更块数/总块数）、可选的整体判定（如 unchanged / minor / major，判定规则显式）。
- **可追溯**：每个变更携带双方版本的块定位（用于 S3 UI 高亮跳转）。

**明确不做**：自动合并、语义级改写归纳（"把公式从 E=mc² 改成了…"这类自然语言摘要归 S3，且用模板拼接而非新模型调用）。

## Acceptance criteria

- [ ] 纯函数 `diff_ir(ir_a, ir_b) -> DiffReport`：不触网、不读文件、确定性（同输入同输出，可快照）。
- [ ] 构造 fixture 覆盖：全同、全换、标题修改、段落移动、公式修改、图表增删、空 IR 边界；每类断言 op 与块类型正确。
- [ ] 相似度阈值行为有边界测试（阈值上下两侧的输入分别判 modified 与 removed+added）。
- [ ] 真实数据验证：取用户库中一个多版本文档（或 fixture 双版本）跑 diff，报告可读且块定位准确（人审记录在 handoff）。
- [ ] 汇总统计与整体判定规则有独立单测（规则表驱动）。
- [ ] CLI 便捷入口（如 `graph2note diff <doc_id> --versions a b`）输出人类可读摘要，便于无 UI 验收（S3 之前的主要消费面）。

## Blocked by

None - can start immediately
