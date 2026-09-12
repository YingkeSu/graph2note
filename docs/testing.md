# 测试分类与模块级运行（issue 12）

> 政策：**单模块开发只跑相关模块测试 + 受影响邻近测试；大版本/发布合并前才跑全量。**
> 分类只做标记与运行方式，不改变任何测试行为、不删除测试；全量套件始终一键可跑。

## 分类维度

测试用 pytest marker 分三个维度标注（数据在 `tests/taxonomy.py`，收集期由
`tests/conftest.py` 自动打标，**不修改测试文件内容**）：

| 维度 | marker | 说明 |
|---|---|---|
| 模块归属（必填，每文件一个） | `ir` `render` `preprocess` `pipeline` `ingest` `verify` `webapp` `notes` `workspace` `visualqa` `eval` `diagrams` `config` `store` `cli` `meta` | 归属哪个功能模块 |
| 层次 | `unit` / `integration` | integration = 跨模块装配/全链/Web/CLI；其余 unit |
| 成本 | `slow` / `live_llm` / `gui` | slow = 较重；live_llm/gui 仅注册供手动/未来使用（本套件无 live/GUI 测试） |

> `live_llm` 用下划线（而非指令草案里的 `live-llm`），避免 `-m live-llm` 被解析成
> 表达式歧义；语义一致。

所有 marker 在 `pyproject.toml` 注册并开启 `--strict-markers`，未知 marker 直接报错。

## 模块级运行

```bash
scripts/run_tests.sh webapp            # 单模块
scripts/run_tests.sh webapp notes      # 多模块（or 组合）
scripts/run_tests.sh --unit            # 全部单元测试
scripts/run_tests.sh --integration     # 全部集成测试
scripts/run_tests.sh --fast            # 排除 slow
scripts/run_tests.sh --all             # 全量（大版本合并前）

# 等价裸命令
uv run pytest -m webapp
uv run pytest -m "webapp or notes"
```

## 模块 → 测试映射表

「改了模块 X 应跑哪些测试」：先跑 X 的 `-m X`；若改动触及**契约/共享依赖**（表右列），
连同邻近模块一起跑。

| 模块 | 测试文件 | 一键 | 契约改动建议连同 |
|---|---|---|---|
| ir | `test_ir.py` | `-m ir` | render、pipeline |
| render | `test_renderer.py` | `-m render` | ir、pipeline |
| preprocess | `test_preprocess.py` | `-m preprocess` | pipeline |
| pipeline | `test_pipeline.py` `test_router.py` `test_route_b.py` `test_vlm.py` `test_cli_parse.py` `test_issue11_parse.py` `test_issue12_twostage.py` `test_ocr.py` `test_e2e_images.py` | `-m pipeline` | ir、render、preprocess |
| ingest | `test_ingest_cluster.py` `test_ingest_hash.py` `test_ingest_missing.py` `test_ingest_pdf.py`（`test_pdf_upload.py` 待 issue 08 合并） | `-m ingest` | store、webapp |
| verify | `test_verify_diff.py` `test_verify_engine.py` | `-m verify` | pipeline |
| webapp | `test_webapp.py` `test_webapp_vault_export.py` `test_webapp_layout.py` `test_documents.py` `test_session_health_cli.py` `test_custom_llm_provider_api.py` | `-m webapp` | pipeline、store |
| notes | `test_vault_exporter.py` `test_incremental_export.py` `test_classify_moc.py` | `-m notes` | store、webapp |
| workspace | `test_collections.py` `test_document_metadata.py` `test_tags.py` `test_timeline.py` `test_graph.py` `test_graph_layout.py`（U4） `test_inbox.py` `test_telemetry.py` | `-m workspace` | store、webapp |
| visualqa | `test_visualqa.py` `test_visualqa_content.py` `test_cli_visualqa.py` | `-m visualqa` | eval |
| eval | `test_dataset.py` `test_editerate.py` `test_gateway.py` `test_gateway_select.py` `test_session_isolation.py` | `-m eval` | config、pipeline |
| diagrams | `test_diagrams.py` `test_issue15_diagram.py` | `-m diagrams` | render、pipeline |
| config | `test_config.py` `test_llm_settings.py` `test_custom_llm_provider.py` | `-m config` | eval、webapp |
| store | `test_store_bridge.py` | `-m store` | webapp、notes、workspace |
| cli | `test_cli.py` | `-m cli` | pipeline、notes |
| meta | `test_taxonomy.py` | `-m meta` | — |

## 新增测试文件的登记

新增 `tests/test_*.py` 时，在 `tests/taxonomy.py` 的 `FILE_TO_MODULE` 登记模块归属；
未登记会被 `test_taxonomy.py::test_every_test_file_has_module_mapping` 拦下。
层次/成本按 `INTEGRATION_FILES` / `SLOW_FILES` 集合判断，默认 unit。

## 全量不变性

分类前后**既有测试的数量、通过/跳过逐项一致**（收集期只加 marker，不改断言/不改测试）；
新增的只有 `test_taxonomy.py` 三个元测试。全量运行：

```bash
OPENCODE_API_KEY=dummy uv run pytest   # 或 scripts/run_tests.sh --all
```
