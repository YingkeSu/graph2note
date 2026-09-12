# Handoff A1 — 解析结果自动打标签（识别→标签闭环）

Branch: `dev/a1-auto-tag` · Issue: `issues/A1-auto-tag-from-recognition.md` · Status → in-review

## 1. 一句话结论

解析完成后的自动打标已经是闭环：单图、PDF 逐页入库都经**同一个 post-ingest 挂钩点**
`autotag.after_ingest` 触发「词表优先」的 LLM 推断，标签以 `provenance=auto` 挂到文档；
编辑器标签区用「自动」角标区分、可一键移除或保留为手工；`tags backfill` 以 dry-run
预算报告 + `--yes` 完成存量回填（真实库 43/43 篇补齐）。推断失败只记 warning，不阻塞解析。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/autotag.py`（新） | `build_prompt`（词表规范标签+别名，`max_chars` 显式截断）、`parse_tag_reply`（提取 `{tags:[...]}` 并过 `validate_tag_inference`）、`infer_tags`（planner 缝，返回校验结果+token usage）、`live_planner`（唯一 live choke point，复用 `eval.gateway`）、`after_ingest`（**统一 post-ingest 挂钩点**，失败→warning 不抛）、`pending_documents`/`backfill`（预算报告与真实执行）、`TagInferrer` |
| `graph2note/store.py` | 标签 provenance 持久化：`tag_provenance` 映射 + `ensure_tag_provenance`/`_merge_tag_provenance`；新增 `add_manual_tags`/`promote_tag`/`remove_tag`/`tag_vocabulary`/`add_tag_alias`/`set_auto_tag_meta`；`add_auto_tags` 改为直接写 auto provenance（不再经 `set_tags` 变手工）；Session 与 File 两实现 |
| `graph2note/webapp.py` | `create_app(..., auto_tag_inferrer=, auto_tag=, auto_tag_model=, auto_tag_provider=, auto_tag_max_chars=)` 注入缝；单图入库后调 `after_ingest`；`POST .../tags/manual`（手工加）、`PATCH .../tags/{tag}`（转手工保留）、DELETE 改用 `remove_tag`；标签端点统一返回 `tag_provenance` + `tags_detail`；`GET /api/documents/{id}` 含每标签 provenance 与 `auto_tag` telemetry |
| `graph2note/pdflib.py` | `process_pdf(..., auto_tag_inferrer=)` 透传；`_parse_one` 逐页 `save_document` 后调同一 `after_ingest` |
| `graph2note/cli.py` | `graph2note tags backfill [--dry-run\|--yes] [--storage\|--limit\|--max-chars\|--model\|--provider\|--json]`，默认 dry-run |
| `graph2note/webstatic/{app.js,style.css}` | auto 标签「自动」角标 + 虚线橙色区分；`✓` 保留为手工；移除走 DELETE 不再整体 PUT；手工新增走 `/tags/manual` |
| `macos/launcher.py` | 生产 app `create_app(auto_tag=True)`（live classify planner）；测试/默认保持禁用（零网络） |
| `tests/test_autotag.py`（新，21 项）+ `tests/golden/autotag-{reuse,new,invalid,alias}.json` | 录制 golden：复用词表 / 新增规范化 / 非法输出被拒 / 别名归并；stub planner 全离线 |
| `tests/taxonomy.py` | 登记 `test_autotag → workspace`（integration） |

## 3. 关键决策

- **单一挂钩点**：`autotag.after_ingest(store, document_id, markdown, inferrer=...)` 是三入口
  唯一的打标接线。`inferrer=None` 时为 no-op，因此测试与默认 `create_app()` 不会触网。
- **挂钩先于 job done**：单图路径在 `save_document` 后、`job.status="done"` 前调用；轮询到
  `done` 即保证标签已在（PDF 页同理，在 `_parse_one` 内）。推断异常被吞成 record 上的
  `auto_tag.status=failed` + `warning`，解析入库不受影响。
- **provenance 只在记录里增加映射，不改 `tags` 数组契约**：`record["tags"]` 仍是字符串数组，
  所有既有消费方（exporter/graph/inbox/timeline/telemetry/搜索）零改动；新增
  `record["tag_provenance"]`。历史记录缺映射时按 `manual` 兜底（保守，只有 A1 显式加的才标 auto）。
- **auto 不覆盖 manual**：`_merge_tag_provenance` 里已存在的 manual 标签不会被后续 auto pass 降级；
  用户 `PUT /tags`（整体替换）会全部转 manual，属于显式语义。
- **词表优先靠两层**：prompt 列出规范标签+别名要求复用；入库 `add_auto_tags` 仍走
  `canonicalize_tags→ensure_tag→resolve_tag`，输出别名会被归并到已有规范标签而不是新建
  （fixture：词表有 `机器学习`（别名 `machine learning`），golden 输出 `machine learning`
  → 归并为 `机器学习`，词表未新增同义标签）。
- **遥测**：每次推断的 `prompt/completion/reasoning/total_tokens`、model、provider 记在
  `record["auto_tag"]["inferences"]`，经文档详情 API 可查（未并入 Dashboard 汇总，见未尽事项）。
- **生产默认开启、测试默认关闭**：`create_app(auto_tag=False)` 默认禁用，避免既有离线测试触网；
  `macos/launcher.py` 传 `auto_tag=True` 用配置的 classify 渠道构建 live planner。CLI backfill
  的 `--yes` 同样懒构建 live planner。
- **live 调用不带 `temperature`**：实测当前 classify 渠道模型拒绝 `temperature=0`
  （HTTP 400 `only 1 is allowed`），故不显式传温度，交给 provider 默认。

## 4. R1（并行）如何接入该挂钩点

R1 的 `repair run` 重跑路径在**新版本入库之后**调用同一函数即可（无需新 API）：

```python
from graph2note import autotag

store.save_document(document_id=doc_id, markdown=new_md, ...)   # 追加 repaired 版本
autotag.after_ingest(
    store, doc_id, new_md,
    inferrer=app.state.auto_tag_inferrer,      # Web 入口
    # 或 CLI: autotag.TagInferrer(planner=autotag.live_planner(provider=..., model=...))
)
```

`after_ingest` 会重写 `record["auto_tag"]` 且 auto 标签幂等合并，因此即使该文档已回填过，
重跑也会用修复后的正文重新推断（旧的 auto 标签保留、新标签补齐；manual 标签永不降级）。

## 5. AC 逐条证据（离线，`tests/test_autotag.py`）

| AC | 证据 |
|---|---|
| 1 推断函数离线可测：复用词表 / 新增规范化 / 非法输出被拒三类 golden，CI 无真实调用 | `test_infer_reuses_vocabulary_golden`（golden `autotag-reuse.json`，`planner.calls==1`）、`test_infer_new_tags_are_normalized`（`Vector-Search`/空格/大小写→`vector search`，去重）、`test_infer_rejects_illegal_output`（`{"tags":"not-a-list"}`→`tags is None`+warning）；所有测试注入 `StubPlanner`，无网络 |
| 2 三入口完成后带 auto 标签；失败时解析仍成功且 warning 可查 | 单图 `test_single_image_parse_attaches_auto_tags`（TestClient `/api/parse`→文档 `tag_provenance` 全 auto）；PDF 页 `test_pdf_page_commit_attaches_auto_tags`（`process_pdf` 真实 PDF，1 次推断）；R1 重跑 `test_repair_rerun_hook_attaches_tags_to_new_version`（同 doc_id 第二版本仍打标、旧版本保留）；失败 `test_after_ingest_failure_keeps_document_and_warns` + `test_after_ingest_invalid_reply_is_a_warning`（文档在、`auto_tag.status=failed`、warning 含原因）、`test_after_ingest_disabled_is_a_noop` |
| 3 auto/manual provenance 在 API 与编辑器 UI 可区分；移除/转手工持久化 | API `test_api_promote_and_remove_auto_tag_persist`（GET 返回 `tag_provenance`/`tags_detail`；PATCH→manual 后新建 store 重载仍 manual；DELETE 后重载标签确删）、`test_manual_add_endpoint_marks_manual`、`test_promote_unknown_provenance_is_rejected`（422）；UI `renderDocumentTags(tags, provenance)` 渲染「自动」角标与 `✓`，移除走 DELETE、新增走 `/tags/manual`（`node --check` 语法通过） |
| 4 词表优先：词表已有「机器学习」，输出「machine learning」应归并 | `test_vocabulary_priority_merges_alias_without_new_tag`（golden `autotag-alias.json`；文档标签=`机器学习`，`list_tags()` 仅 `{机器学习, 知识库}`，无同义新标签） |
| 5 `tags backfill` 默认 dry-run，报告数=实际调用数；`--yes` 补齐存量并在 handoff 记真实结果与预算 | `test_backfill_dry_run_reports_budget_without_calls`（3 篇含 1 已 ok/1 空→pending=2，planner 0 调用）、`test_backfill_yes_calls_match_report`（`planner.calls == dry.estimated_calls == 2`，第二次 dry-run pending=0）、`test_backfill_limit_caps_budget`、CLI `test_cli_backfill_defaults_to_dry_run`（无 `--yes` 即 dry-run）、`test_cli_backfill_yes_uses_injected_planner`；真实库结果见 §6 |
| 6 遥测记录每次推断 token；既有 tags/store 测试全绿 | `test_after_ingest_attaches_tags_and_records_usage`（`auto_tag.inferences[0].total_tokens==138`、model/provider）；全量 `uv run pytest` → **501 passed**（基线 480 + 新增 21） |

## 6. 真实库回填（维护者已授权；`~/Library/Application Support/Graph2Note/storage`）

预算纪律：先 dry-run 核对，再 `--yes` 执行。

| 阶段 | dry-run 预估 | 实际调用 | 结果 |
|---|---|---|---|
| 第一次 dry-run | 43 篇 / 43 次 | — | 全库 43 篇均待回填（此前无 auto_tag） |
| 第一次 `--yes` | 43 | 43 | **成功 0 / 失败 43**：live planner 传了 `temperature=0`，当前 classify 渠道模型拒绝（HTTP 400 `only 1 is allowed`）；0 token，失败均落 `auto_tag.warning` |
| 修复后 `--yes --limit 1` | 1 | 1 | 成功 1（832 tokens） |
| 第二次 dry-run | 42 篇 / 42 次 | — | 1 篇已 ok |
| 第二次 `--yes` | 42 | 42 | **成功 42 / 失败 0**，85,930 tokens |

- **最终存量状态**：43/43 文档 `auto_tag.status=ok`，pending=0；标签关系 289 条全部
  `provenance=auto`；落库词表 243 个规范标签（含模型复用别名产生的锚点）。
- **预算对账**：两轮 dry-run 报告数（43、42）分别等于两轮实际推断调用数（43、42）；
  真实 LLM 调用共 86 次（其中 43 次为首轮 transport 失败，0 token），成功推断 43 次。
  失败例外全部是第一轮的 `temperature` 参数问题，已在代码中修复并不会再发生。
- 回填样例：`doc-d96685d5f7 → 控制理论、状态空间模型、对角标准型…`；
  `doc-75d37e7d26 → 手稿电子化、ocr识别、markdown转换…`。

## 7. 如何运行

```bash
scripts/run_tests.sh workspace                 # 含 test_autotag
uv run pytest tests/test_autotag.py            # 21 passed
uv run pytest                                  # 501 passed（全量离线，零真实网络）

# 存量回填（默认 dry-run，核对后加 --yes）
uv run python -m graph2note.cli tags backfill --dry-run
uv run python -m graph2note.cli tags backfill --yes [--limit N]
```

## 8. 未尽事项 / 建议

1. **auto-tag token 未并入 Dashboard 汇总**：已逐次记录在 `record["auto_tag"]["inferences"]`
   并经 API 可查；`telemetry.build_stats` 仍只统计解析版本事件。若要并入看板，建议把 auto_tag
   记为独立事件源，避免与解析事件重复计费。
2. **classify 渠道温度约束**：live planner 不传 `temperature`；若换到需要固定温度模型，
   可在 `autotag.live_planner` 增加显式参数（当前为兼容实测渠道而省略）。
3. **回填与 R1 的时序**：本轮已对含黑图的存量文档打标；R1 重跑后按 §4 挂钩点会自动重推断，
   建议 R1 验收时抽查其重跑文档的 `auto_tag` 已随新版本刷新。
4. **UI 视觉**：`app.js` 渲染路径已 `node --check`，标签区改动内聚（未动编辑器整体布局）；
   本轮未在 AO Browser panel 做像素级复核，U3 迁移工作区时请保持「自动角标 + 保留/移除」行为。
5. **别名治理入口**：新增的 `store.add_tag_alias` 目前仅测试使用；如需在词表页维护别名，
   可在 U 系视图加一个显式入口（本 issue 未要求）。

## 9. 相关文件

- 实现：`graph2note/autotag.py`、`graph2note/store.py`、`graph2note/webapp.py`、`graph2note/pdflib.py`、`graph2note/cli.py`
- 前端：`graph2note/webstatic/{app.js,style.css}`；生产入口 `macos/launcher.py`
- 测试：`tests/test_autotag.py`、`tests/golden/autotag-*.json`、`tests/taxonomy.py`
- 上游：`../knowledge-workspace/issues/02-tag-vocabulary-governance.md`（词表治理与录制 golden 口径）
