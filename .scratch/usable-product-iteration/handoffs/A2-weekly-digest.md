# Handoff A2 — 每周小结（范围内材料的周期性汇总）

Branch: `dev/a2-weekly-digest` · Issue: `.scratch/usable-product-iteration/issues/A2-weekly-digest.md` · Status → in-review

## 1. 一句话结论

「每周小结」已按需、可重复、可追溯地交付：给定 本周/上周/自定义 范围，范围内文档
（有效时间优先级链，无有效时间回退导入时间；PDF 来源页文档一并纳入）经**确定性组装 + 指纹**后，
走 `notes/llm.py` 文本通道做**单次** LLM 调用，生成 Markdown 小结并落盘 `digests/<id>.md` +
`<id>.meta.json`；**同指纹重复请求零增量调用**，`force=true` 才重生成新版本。API
（`POST/GET /api/digests`、`GET /api/digests/{id}`）、数据看板「每周小结」区块与可选
CLI `graph2note digest` 三层入口齐备；空范围返回明确空态且不调用模型。全链离线测试
（录制 golden）覆盖组装→调用→落盘→API→UI，purpose session 与 token 遥测均已接入。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/digest.py`（新，~700 行） | 核心：`resolve_range`（本周/上周/自定义，日历周稳定）、`select_effective_time`（四时间戳优先级链 + 导入时间回退）、`documents_in_range`（纯函数，含 PDF 来源文档）、`assemble_material`（确定性排序 + 截断 + 指纹 + prompt）、`compute_fingerprint`、`render_digest_markdown`（追加来源清单）、`digests_dir/list_digests/load_digest/find_cached/save_digest`（唯一 IO）、`generate_digest`（缓存/单次调用/落盘）、`digest_session`（purpose 会话隔离）、`resolve_digest_channel`、`normalize_usage` |
| `graph2note/notes/llm.py` | `_gateway_text_usage`（在 `_gateway_text` 之上返回 `text+usage`，新增 `session` / `temperature` / `max_tokens` 可选参数）；`_gateway_text` 行为不变（默认 `temperature=0`、`max_tokens=4096`） |
| `graph2note/telemetry.py` | `build_stats(..., digest_records=None)` + `_digest_events`：小结 token/成本并入 `model_usage` 与日/月 token 桶，**不影响**文档计数与遥测质量口径 |
| `graph2note/webapp.py` | `create_app(..., digest_planner=None)` 注入缝 + `POST /api/digests`、`GET /api/digests`、`GET /api/digests/{id}`；`/api/stats` 传入 digest meta |
| `graph2note/cli.py` | `graph2note digest --week this\|last \| --from --to [--force] [--json] [--storage]` |
| `graph2note/webstatic/index.html` | `#dashboard-zone` 内新增 `#digest-panel`（范围选择 + 自定义起止 + 强制重生成 + 生成按钮 + 历史列表 + 查看器），不重排看板整体布局 |
| `graph2note/webstatic/app.js` | `renderDigestPanel/loadDigestHistory/openDigest/generateDigest/showDigestMarkdown`；抽出 `renderMarkdownInto` 复用现有 marked+KaTeX 渲染；空态文案与缓存/生成状态提示 |
| `graph2note/webstatic/style.css` | digest 区块样式（`.digest-*`，含窄屏单列） |
| `tests/test_weekly_digest.py`（新，31 项） | 范围映射/指纹缓存/遥测/落盘/API/DOM/CLI 全部离线 |
| `tests/golden/weekly-digest.golden.md`（新） | 录制的 LLM 输出 golden（离线全链复用） |
| `tests/taxonomy.py` | 登记 `test_weekly_digest → notes`（integration） |

## 3. 关键决策

- **本周=日历周（周一~周日），不截到今天**：范围整周稳定，指纹不会每天漂移，避免无谓的模型调用
  （预算纪律）。上周=上一个周一~周日。
- **有效时间链与「回退导入时间」分离**：`select_effective_time` 先走 `document_time > capture_time >
  import_time`（兼容标量别名），三者皆空时回退到 `created_at`（导入时间），`source=import_fallback`；
  仍无则返回 `None`，该文档被排除（不崩、不误纳）。
- **指纹 = 范围起止 + 每篇 (document_id, version_id, content_hash) 的规范 JSON SHA-256**：范围只取
  from/to（kind 不参与），同一库状态必得同一指纹；内容或版本任一变即 miss。命中即复用，`llm_calls=0`。
- **确定性组装**：按 `(有效日期, document_id)` 排序（与 store 迭代顺序无关）；单篇正文上限
  `MAX_DOC_CHARS=2000`；`MAX_DOCS=60`，超出取最近 60 篇并在 meta 记 `omitted_documents`。
- **来源清单由系统追加**：prompt 明确要求模型不要输出来源；`render_digest_markdown` 追加
  `## 来源` + `[标题](#doc/<id>)（<id>）`，链接复用 SPA 的 `#doc/<id>` 路由，可点回文档。
- **purpose 会话隔离**：小结专用 `graph2note-digest-01`，env 覆盖 `GRAPH2NOTE_SESSION_DIGEST` >
  `GRAPH2NOTE_DIGEST_SESSION`；与 parse/eval/verify/routeb/diagram/classify 均不同，沿既有网关纪律
  （未改 `eval/gateway.py`）。
- **文本通道复用**：`generate_digest` 默认 planner = `notes.llm._gateway_text_usage`（`_gateway_text`
  的 usage 版），测试注入录制 golden planner。
- **模型兼容性修正（真实冒烟暴露）**：kimi-k3 只接受自己的 temperature，显式 0 会被 400 拒绝 →
  小结调用 `temperature=None`（省略字段）；同时 kimi-k3 为 thinking-only，4096 输出预算会被推理占满
  导致正文截断 → 小结调用 `max_tokens=MAX_SUMMARY_TOKENS=8192`。两者都用离线 payload 断言锁住，
  且不改变 classify 的既有默认（0 / 4096）。
- **遥测并入但不污染文档口径**：digest 事件 `document_id="digest:<id>"` 只进 model_usage 与 token
  桶；`periods/trend/quality/new_documents` 仍只统计文档事件（有专测证明 `plain == merged`）。
- **看板区块最小插入**：只新增 `#digest-panel` 作为 `#dashboard-content` 的同级，不改现有面板/网格；
  即使库为空（`empty_library`）小结区块仍独立渲染自己的空态。U1 若重构 dashboard zone，迁移此区块即可。

## 4. AC 逐条证据

| AC | 证据 |
|---|---|
| 1 范围→文档集合纯函数（优先级链回退/空范围/PDF 来源） | `test_select_effective_time_priority_chain_and_import_fallback`（manual>inferred document/capture/import + `created_at` 回退 + 全空 None）、`test_documents_in_range_filters_sorts_and_is_pure`（乱序输入同结果）、`test_documents_in_range_is_inclusive_on_both_boundaries`、`test_empty_range_is_empty_not_an_error`、`test_pdf_source_documents_are_included`（`pdf_id/page_index` 文档纳入）、`test_resolve_range_calendar_weeks_custom_and_errors` |
| 2 同指纹零增量调用 + force 新版本 | `test_same_fingerprint_reuses_cache_with_zero_new_calls`（录制 planner `calls==1`，第二次 `cached=True/llm_calls=0`，仅 1 个 meta）、`test_force_regenerates_and_writes_a_new_version`（`calls==2`、新 digest_id、同指纹、2 个 meta）、`test_changed_content_misses_the_cache`（v1→v2 指纹变化） |
| 3 文本通道 + purpose 隔离 + token 进遥测 | `test_digest_purpose_session_is_isolated_and_env_overridable`（默认 `graph2note-digest-01` 且不等于任何既有 session；env 可覆盖）、`test_digest_live_seam_omits_temperature_and_raises_max_tokens`（live 缝传 session/`max_tokens`，省略 temperature）、`test_generation_records_usage_in_meta_and_metadata`（usage 落 meta，prompt 含组装材料）、`test_stats_merge_digest_tokens_without_inflating_document_counts`（digest token 进 `model_usage` + 日桶，文档计数/质量不变） |
| 4 落盘含 meta，重启后可读 | `test_digest_is_persisted_with_meta_and_readable_after_restart`（仅带 storage 目录重扫：`list_digests`/`load_digest` 读回 range/fingerprint/document_ids/model/usage 与 md 正文+来源）、`test_list_digests_ignores_corrupt_meta_files` |
| 5 golden 离线全链 + CI 零真实调用 + 真实冒烟 1 次 | `test_full_chain_offline_golden_plan_to_api_and_ui`（`tests/golden/weekly-digest.golden.md` 注入 planner：组装→调用→落盘→`POST/GET /api/digests`→`/api/stats`→DOM 断言；无网络）、`test_api_empty_range_returns_explicit_empty_state`、`test_api_rejects_bad_range_and_reports_model_errors`；全部测试用注入 planner，CI 无真实调用。真实冒烟见 §5 |
| 6 API 契约 + Web DOM 断言 + 空态 | 契约：`test_full_chain_offline_golden_plan_to_api_and_ui`（POST 载荷键、list `total/digests`、单个 GET、404）+ `test_api_rejects_bad_range_and_reports_model_errors`（422/502）；DOM：`id="digest-panel/range/from/to/generate/history/viewer/viewer-content"` + app.js 含 `/api/digests`、`renderDigestPanel`、`renderMarkdownInto`、空态文案；`test_digest_panel_is_scoped_to_dashboard_zone`（区块在 dashboard 内、upload 之前）；空态：`test_api_empty_range_returns_explicit_empty_state` 断言 `该范围内没有材料`。另：AO Browser 面板对真实库可视复核见 §5 |

离线测试统计：`uv run pytest tests/test_weekly_digest.py` → **31 passed**；
全量 `uv run pytest` → **547 passed**（含既有 telemetry/webapp/cli/notes 无回归）。
`node --check graph2note/webstatic/app.js` 通过；HTML 解析无未闭合标签、无重复 id。

## 5. 真实冒烟（预算使用与人审）

维护者授权 1 次真实调用。对**真实用户库**（`~/Library/Application Support/Graph2Note/storage`，43 篇）
执行单次生成：

```
graph2note digest（等价脚本调用）
range       本周（2026-09-07 ~ 2026-09-13）
documents   43 / omitted 0
digest_id   dg-20260912104158-76f34c85
fingerprint 76f34c85dab77059c2730dedf1353797bff342d00bec2d20dea4b2b4c99b97d8
model       kimi-k3 (provider=kimi, session=graph2note-digest-01)
usage       prompt=37386 completion=4096 reasoning=3431 total=41482
elapsed     115.7s   （gateway=kimi，文本通道）
落盘        digests/dg-20260912104158-76f34c85.{md,meta.json}
```

- **计费调用 = 1 次**（该次成功生成并落盘）。过程中 2 次尝试被网关即时 400 拒绝
  （`invalid temperature: only 1 is allowed for this model`），**未产生 completion token**，不计入预算；
  据此修正为省略 temperature（§3）。
- **发现并修复**：该次生成正文在 `max_tokens=4096` 处被截断（`completion_tokens==4096`，其中
  reasoning 3431），模型正文约 1017 字即断。已将小结输出预算提升为
  `MAX_SUMMARY_TOKENS=8192` 并新增离线 payload 断言（`test_digest_live_seam_*` /
  `test_gateway_text_usage_payload_*`）。为严格守 1 次预算，**未**再次真实调用；建议维护者日后以
  `graph2note digest --week this --force` 重跑一次以获得完整正文（指纹不变，需 `--force`）。
- **UI 人审（AO Browser 面板，真实库）**：数据看板「每周小结」区块渲染正常——范围下拉（本周）、强制
  重生成、历史列表（`本周（2026-09-07 ~ 2026-09-13） · 43 篇 · kimi-k3 · 41482 tokens`）、查看器
  展示 Markdown 正文 + `## 来源` 可点链接（`#doc/<id>`），指纹与来源数正确。空态/自定义范围由离线
  测试覆盖。

## 6. 如何运行

```bash
uv run pytest tests/test_weekly_digest.py      # 31 passed（离线，零真实调用）
uv run pytest -m "notes or webapp or workspace" # 相关模块
uv run pytest                                  # 547 passed

# CLI（离线空态示例；有材料时会走真实文本通道）
python -m graph2note.cli digest --week this --storage "<library>"
python -m graph2note.cli digest --from 2026-09-01 --to 2026-09-07 --force
python -m graph2note.cli digest --week last --json
```

> 注：CLI/服务需在装有可选依赖（numpy 等，`uv run --extra all` 或项目既有 conda 环境）的解释器下运行；
> `graph2note.notes.llm` 的导入链会经 `notes.exporter → ingest.hash` 触达 numpy。

## 7. 未尽事项 / 建议

1. **真实冒烟正文截断**：已把输出预算提到 8192（离线锁定）；建议维护者 `--force` 重跑一次确认完整正文，
   本次受 1 次预算约束未重跑。
2. **输出预算/模型**：kimi-k3 thinking-only，推理会占用输出预算；若后续在设置页把 classify/summary
   用途切到非 thinking 文本模型，可下调 `MAX_SUMMARY_TOKENS`。A3（自定义 LLM）可在渠道层统一处理
   temperature/预算差异，届时 `_gateway_text_usage` 的两个可选参数可被渠道配置取代。
3. **素材规模**：当前整库 43 篇 ≈ 70k 字符 prompt（一次调用可完成，但成本随库增长）。`MAX_DOCS=60`
   为硬上限；若单周材料显著超限，建议后续按主题分组分多次小结（当前未做，避免过度设计）。
4. **缓存清理/保留策略**：`digests/` 只增不减，历史列表按时间倒序。未做删除/保留上限，若需要可加管理入口。
5. **CLI 错误码**：`--json` 模式下即使 `status=error` 也返回 0（JSON 内含 message）；非 JSON 模式 error 返回 1。
   如希望脚本化严格失败，可再议。

## 8. 相关文件

- 实现：`graph2note/digest.py`、`graph2note/notes/llm.py`、`graph2note/telemetry.py`、
  `graph2note/webapp.py`、`graph2note/cli.py`、`graph2note/webstatic/{index.html,app.js,style.css}`
- 测试：`tests/test_weekly_digest.py`、`tests/golden/weekly-digest.golden.md`、`tests/taxonomy.py`
- 上游：`.scratch/usable-product-iteration/issues/A2-weekly-digest.md`、`ISSUE-DRAFT.md`
- 领地相关：U1（dashboard zone 重构时迁移 `#digest-panel`，行为保持）；A3（渠道层 temperature/预算差异统一）
