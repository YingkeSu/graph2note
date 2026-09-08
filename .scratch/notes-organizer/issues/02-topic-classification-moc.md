# 分类归纳引擎 + MOC 索引笔记

Status: in-review

## Parent

[PRD](../PRD.md)（notes-organizer feature）。

## What to build

让导出的 vault 按内容语义自组织。端到端行为：`全部文档内容（IR/Markdown 文本）→ LLM 主题分类 → 分类方案（schema 校验、可人工调整）→ vault 落地（分类文件夹 + 标签 + 每主题 MOC 索引笔记）`。

- 分类归纳用网关文本模型（无视觉需求；调用参数见 `docs/llm/opencode-go.md`），对文档集做主题聚类与命名。
- 分类方案为机器可校验结构：类别树（一级分类 ≤ 8，小语料宜粗）+ 每文档归属 + 一句话摘要；方案可人工调整后重导出。
- 每个主题生成 MOC 索引笔记：该主题全部笔记的 wiki links + 每篇一句话摘要。
- 分类输出用录制 golden fixtures 测试；CI 不 live 调用。

## Acceptance criteria

- [x] 分类方案有 schema 校验，非法方案被拒绝且不进入导出 — `test_validate_allows_good_scheme`/`test_validate_rejects_invalid`/`test_empty_docset_is_valid`
- [x] MOC 生成覆盖全部类别与全部文档（每篇笔记至少被一个 MOC 收录，链接可达）— `test_moc_covers_all_docs_and_categories`（链接经 exporter 校验无死链）
- [x] 一级分类数量受上限约束（>8 时合并或报错，测试覆盖）— `test_exactly_max_topics_ok`（N=8 通过）+ `validate_rejects_invalid` 中 9 类别用例（N>8 报错）
- [x] 人工调整分类方案后可重跑导出并生效 — `test_persist_topics_and_human_adjust`（调整后 doc 进入新 MOC）
- [x] golden fixtures 覆盖：空文档集、单主题、多主题、类别命名的中英文输出 — `tests/golden/classify-empty|single|multi|cn|en.json` → `test_golden_scheme_export_offline`/`test_golden_empty_export`
- [x] 全部测试离线运行，CI 无 live 调用 — LLM planner 注入；无网络

## Blocked by

- 01-vault-exporter
