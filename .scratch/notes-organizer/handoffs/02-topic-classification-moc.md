# Handoff — notes-organizer Issue 02：分类归纳引擎 + MOC 索引笔记

**Status: in-review** · Track A worker：graph2note-2 · Branch：`dev/no02-classification-moc`
**Verified:** 全离线（分类器注入/规则纯函数/golden fixtures，零网络）· 全套 `pytest`：**207 passed / 2 skipped**

---

## 1. 核心交付

在 `graph2note/notes/` 新增三个模块，并扩展 exporter 与 07 store：

| module | role |
|---|---|
| `classify.py` | `ClassificationScheme`（类别树 ≤8 + 每文档归属 + 一句话摘要）与 **schema 校验** `validate_scheme()`（非法即抛 `SchemeError`，绝不进入导出）；**确定性规则分类器** `rule_classify()`（默认/离线兜底，关键词映射，未命中归入「杂项」，保证每篇至少一个 topic）+ `classify_documents()`（分类器插件缝 → 统一过 schema 校验）+ `apply_scheme()`（把 topics 写回 07 `DocumentRecord`）。 |
| `llm.py` | **文本模型**分类（chat/completions，非视觉；muse 系禁用）：`build_prompt()`、`parse_scheme_json()`（平衡括号 JSON 提取）、`classify_via_llm()`；**planner 可注入**——离线测试注入 golden reply，CI 零 live 调用；默认 `_gateway_text()` 走 opencode，`OPENCODE_API_KEY` 运行时读 env。 |
| `moc.py` | 每主题一张 MOC 索引笔记（frontmatter + 收录计数 + 相对 markdown 链接到各文档笔记 + 一句话摘要），**确定性**：同输入同输出。 |
| `export_vault()` 扩展 | 新增 `scheme=` 参数 → 在 `mocs/` 写每主题 MOC，纳入链接校验与 manifest（`moc_files`）。 |
| `store.py` 扩展 | 新增 `DocumentStore.set_topics(document_id, topics)`（Session 内存 + File 落盘 record.json；**不改 updated_at**，避免分类打乱列表排序）；`loader` 已读 `rec["topics"]`，写回后自动流通到导出。 |

### 端到端链路
```
documents(Markdown/IR 文本) → (rule_classify | LLM) → ClassificationScheme
→ validate_scheme (≤8/归属/摘要) → apply_scheme(store) [topics 持久化到 record]
→ load_entries(store) [topics 随 entry 携带]
→ export_vault(entries, scheme=scheme) → notes(带 frontmatter topics) + mocs/ 每主题 MOC
```

## 2. Key decisions

- **MOC 用相对 markdown 链接**（`[title](../notes/<safe_id>/note.md)`）而非裸 wiki 链接：note 文件位于每文档子目录且名恒为 `note.md`，裸 `[[<id>]]` 无法唯一定位；相对链接经 exporter 链接校验器正确解析、Obsidian 原生兼容。理由写入代码 docstring 与本节。
- **分类器双实现、统一过 schema**：规则版（确定性、离线、兜底）+ 文本 LLM 版（真实质量）。无论来源，`classify_documents` 一律 `validate_scheme` 门禁——非法方案（类别数/归属/摘要）**被拒绝，不进入导出**。
- **一级分类 ≤8 上限**：`validate_scheme(max_topics=8)`，>8 报错（"合并或报错"，本实现取报错 + 测试覆盖）。
- **人工调整可重跑生效**：分类方案是普通数据（`ClassificationScheme`），改 topics/assignments/summaries 后 `apply_scheme` 重写记录 or 直接以新 scheme 导出，即可生效（测试覆盖「调整后 b 归入数学并进入新 MOC」）。
- **topics 持久化不触发 updated_at**：分类是元数据非正文编辑，避免 autosave 与库列表排序被打乱。
- **JSON 解析健壮**：`parse_scheme_json` 用平衡括号 + 字符串状态机提取首个顶层对象（嵌套 assignments 也能解析），残缺/无 JSON 抛 `SchemeError`。

## 3. 验证

```bash
python3 -m pytest tests/test_classify_moc.py -q   # 23 passed（全离线）
python3 -m pytest -q                                 # 207 passed / 2 skipped（全套）
```

覆盖 AC：schema 校验（非法：>8 类别、未知 topic、未知文档、文档未归属、缺摘要——均拒绝）；合法方案通过；MOC 覆盖全部类别与全部文档（每篇 ≥1 MOC，链接经校验可达，死链即失败）；一级分类上限测试（9 类别拒绝、恰 8 通过、空文档集合法）；人工调整重跑生效 + topics 持久化到记录（reload 可见、随导出流通）；golden fixtures 空/单主题/多主题/中文/英文类别命名（`tests/golden/classify-*.json`，经 `validate`+`export` 断言 MOC 落位与 manifest）；LLM 注入 planner（合法回复通过、缺摘要回复被拒、垃圾文本被拒）全离线无 live 调用。

## 4. 已知限制 / 后续

- **live LLM 未在本交付调用**（预算 ≤6 与 CI 零调用约束；只提供回路 + 注入 seam）。真实分类质量与模型选择留待人工/后续评估。
- **MOC 文件名 ASCII 化**：`_safe_name` 保留 Unicode 词字符（中文主题文件名可含中文，如 `mocs/数学.md`），非法路径字符替换为 `_`；仍确定性、无碰撞。
- **深分类/层级/MOC 反链（回链列表）**：PRD User Story 需的精细层级与非一级分类非本 AC；当前 MOC 平铺、每主题一张。
- **分类报告/UI 预览确认**（PRD 开放问题）：当前关闭（手动改 scheme 重跑即可），未做 UI。
- **无密钥提交**：`llm.py` 运行时才读 `OPENCODE_API_KEY`；无 `.env` 入库。

## 5. 手工冒烟（一次性，本机）

```python
# 建 3 份真实记录（webapp 上传或直接 seed）后：
from graph2note.store import FileDocumentStore
from graph2note.notes.classify import classify_documents, apply_scheme
from graph2note.notes.loader import load_entries
from graph2note.notes.exporter import export_vault
store=FileDocumentStore("/tmp/nostore")
entries=load_entries(store)
scheme=classify_documents(entries)          # 规则版离线分类
apply_scheme(store, scheme)                  # topics 写回记录
out=export_vault(load_entries(store), "/tmp/vault", scheme=scheme)
# Obsidian 打开 /tmp/vault：notes/*/note.md 带 frontmatter topics，
# mocs/<主题>.md 索引各主题笔记（相对链接），export-manifest.json 含 moc_files。
```