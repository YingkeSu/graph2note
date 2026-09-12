"""测试分类数据（issue 12）。

三个维度的映射表，供 ``tests/conftest.py`` 在收集期自动打 pytest marker：

- 模块归属：每个测试文件恰好一个模块（mandatory，AC1）。
- 层次：unit / integration。
- 成本：slow / live_llm / gui（live_llm 与 gui 仅注册供手动/未来使用，本套件无 live/GUI 测试）。

新增测试文件请在此登记模块归属；未登记的 ``tests/test_*.py`` 会被
``tests/test_taxonomy.py`` 的覆盖断言拦下（在途分支 07/08/black-fix 的新文件
已预登记：``test_pdf_upload``、``test_webapp_vault_export``、``test_preprocess``）。
"""

from __future__ import annotations

# 模块归属：测试文件 stem -> 模块 marker
FILE_TO_MODULE: dict[str, str] = {
    # IR schema 与校验
    "test_ir": "ir",
    "test_semantic_diff": "ir",  # issue S1（纯引擎）
    "test_versiondiff": "ir",  # issue S3（版本对比 payload/模板摘要）
    "test_evolution": "workspace",  # issue S2（版本链 + pHash 候选规则）
    # 确定性 Markdown 渲染
    "test_renderer": "render",
    # 图像预处理
    "test_preprocess": "preprocess",
    # 解析管线（preprocess -> router -> vlm -> render）
    "test_pipeline": "pipeline",
    "test_router": "pipeline",
    "test_route_b": "pipeline",
    "test_vlm": "pipeline",
    "test_cli_parse": "pipeline",
    "test_issue11_parse": "pipeline",
    "test_issue12_twostage": "pipeline",
    "test_ocr": "pipeline",
    "test_e2e_images": "pipeline",
    # PDF 拆页 / 去重 / 缺页（ingest 包）
    "test_ingest_cluster": "ingest",
    "test_ingest_hash": "ingest",
    "test_ingest_missing": "ingest",
    "test_ingest_pdf": "ingest",
    "test_pdf_upload": "ingest",  # issue 08（新文件）
    "test_pdf_job_recovery": "ingest",  # issue 09（新文件）
    "test_pdf_search": "webapp",  # issue 10（新文件）
    "test_pdf_qa": "webapp",  # issue 11（新文件）
    "test_pdf_qa_multiturn": "webapp",  # P1（新文件）
    "test_ask_view": "webapp",  # P2（新文件，问答一级视图）
    # 双模型交叉验证
    "test_verify_diff": "verify",
    "test_verify_engine": "verify",
    # 本地单用户 Web 应用
    "test_webapp": "webapp",
    "test_webapp_layout": "webapp",  # U1（新文件）
    "test_webapp_editor_workspace": "webapp",  # U3（新文件）
    "test_webapp_vault_export": "webapp",  # issue 07 在途会修改内容；只读参考
    "test_repair": "webapp",  # R1 黑图修复闭环（CLI + API + Web）
    "test_documents": "webapp",
    "test_evolution_api": "webapp",  # issue S2（版本链/候选 API 契约）,
    "test_versiondiff_api": "webapp",  # issue S3（版本对比 API/静态接线）
    "test_session_health_cli": "webapp",
    # Obsidian 导出 / 分类 / MOC
    "test_vault_exporter": "notes",
    "test_incremental_export": "notes",
    "test_classify_moc": "notes",
    "test_weekly_digest": "notes",  # issue A2（每周小结）
    # knowledge-workspace（collections/graph/inbox/metadata/tags/timeline/telemetry）
    "test_collections": "workspace",
    "test_document_metadata": "workspace",
    "test_tags": "workspace",
    "test_autotag": "workspace",  # A1: 识别自动打标签
    "test_timeline": "workspace",
    "test_graph": "workspace",
    "test_inbox": "workspace",
    "test_telemetry": "workspace",
    # 视觉 QA 开发工具（UI / 内容）
    "test_visualqa": "visualqa",
    "test_visualqa_content": "visualqa",
    "test_cli_visualqa": "visualqa",
    # 评估 harness 与网关
    "test_dataset": "eval",
    "test_editerate": "eval",
    "test_gateway": "eval",
    "test_gateway_select": "eval",
    "test_session_isolation": "eval",
    # diagram/flow 确定性渲染
    "test_diagrams": "diagrams",
    "test_issue15_diagram": "diagrams",
    # 运行配置 / LLM 设置
    "test_config": "config",
    "test_llm_settings": "config",
    "test_custom_llm_provider": "config",  # issue A3（自定义供应商存储/网关路由）
    "test_custom_llm_provider_api": "webapp",  # issue A3（设置 API/UI）
    # 文档库持久化
    "test_store_bridge": "store",
    # CLI 入口
    "test_cli": "cli",
    "test_semantic_diff_cli": "cli",  # issue S1（diff 子命令）
    # 测试基础设施自身
    "test_taxonomy": "meta",
}

# 层次：integration = 跨模块装配 / 全链 / Web / CLI；其余为 unit
INTEGRATION_FILES: frozenset[str] = frozenset({
    "test_webapp",
    "test_webapp_vault_export",
    "test_repair",
    "test_documents",
    "test_e2e_images",
    "test_pipeline",
    "test_cli",
    "test_cli_parse",
    "test_cli_visualqa",
    "test_session_health_cli",
    "test_issue11_parse",
    "test_issue12_twostage",
    "test_verify_engine",
    "test_ingest_pdf",
    "test_autotag",
    "test_semantic_diff_cli",
    "test_custom_llm_provider_api",  # issue A3（新文件）
    "test_evolution_api",  # issue S2（版本链/候选 API 契约）
    "test_versiondiff_api",  # issue S3（版本对比 API/静态接线）
    "test_weekly_digest",   # issue A2（新文件）
})

# 成本：slow = 较重（TestClient 全链 / 全链装配 / 图渲染）
SLOW_FILES: frozenset[str] = frozenset({
    "test_webapp",
    "test_webapp_vault_export",
    "test_documents",
    "test_e2e_images",
    "test_issue15_diagram",
})

MODULE_NAMES: tuple[str, ...] = tuple(sorted(set(FILE_TO_MODULE.values())))
