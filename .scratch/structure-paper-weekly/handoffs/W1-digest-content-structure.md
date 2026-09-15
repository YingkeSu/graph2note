# W1 — 周报内容结构与材料策略优化（handoff）

Status: **ready-for-review**
分支：`dev/W1-digest-content`（基线 `main 3c64d60`；AO worktree 建在 `2fd1f98` 后已 `--ff-only` 到 `3c64d60`，无历史改写）
提交：`3b10e57`（四节骨架 + 分节填充 + 材料预算）、`5aea825`（主题脉络材料分区修复）
日期：2026-09-15
领地：`graph2note/digest.py`（独占）、`tests/test_digest*.py`（新增两个文件）。
另动：`tests/test_weekly_digest.py`（既有周报测试，行为改造后必须同步）、`tests/taxonomy.py`（**只追加 2 行**测试文件登记，防 `test_taxonomy` 拦截）。
**未动**：`graph2note/webapp.py`（无需：`/api/digests` 现有三段原样返回 meta，`sections` 随 meta 自动出）、`graph2note/telemetry.py`、`webstatic/index.html`、`webstatic/js/views/dashboard.js`（W2 领地）、`ir.py`、`diagram*`、`papers/*`、`.scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md`（脏文件）。
未 push；未 `find /Users/suyingke`；密钥未进任何产物与提交。

---

## §0 总览（对照 issue 验收项）

| # | 验收项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 四节确定性骨架（标题/顺序固定） | **达成** | `SECTION_DEFS` 常量；`test_section_definitions_are_fixed_titles_in_fixed_order`、`test_generated_markdown_carries_the_four_sections_in_order`（位置单调 + 来源脚注在最后）；fallback/节缓存路径同样四节 |
| 2 | 概览统计为纯函数、不经 LLM、与构造库状态一致 | **达成** | `compute_stats` 纯函数（`_stats_for`），概览正文 `render_overview_body` 全部来自它；`test_overview_numbers_are_deterministic_and_never_asked_of_the_model`（prompt 里不含 `"overview"`、不含统计行）、`test_stats_never_touch_a_model`（把 text 通道打成抛异常仍通过） |
| 3 | 每节 `source_document_ids` 与实际引用一致 | **达成** | 概览=范围内全集；摘录=被摘录子集；模型节=模型声明并校验后（未知 id 丢弃，不伪造）；`test_section_source_ids_match_what_each_section_cites`、`test_parse_section_reply_validates_schema_and_drops_unknown_ids`（golden 里故意放 `doc-not-in-material`） |
| 4 | meta 含 `sections` 且重载成立；旧 meta 读取不炸 | **达成** | `meta_sections()` 校验归一；`load_digest` 返回 `sections`（旧 meta → `[]`）；`test_meta_records_sections_and_reloads_them`、`test_legacy_meta_without_sections_loads_and_lists`、`test_api_serves_legacy_digest_meta_without_sections` |
| 5 | 指纹缓存延续：同指纹零调用；`force=True` 才重生成 | **达成**（并升级） | 整报缓存原语义不变（既有 A2 用例全绿）；`force` 同时绕过整报与节级缓存（`test_force_bypasses_both_caches`）；节级指纹：`test_section_cache_reuses_the_unchanged_section`、`test_section_cache_can_skip_the_model_entirely`（版本号变、正文没变 → `llm_calls=0`） |
| 6 | 材料预算策略可解释、纯函数、有测试、阈值集中 | **达成** | `apply_material_budget`（有效时间优先 + 各主题保底 `TOPIC_FLOOR`），报告进 `material["budget"]`/`meta["budget"]/`stats`，并由概览渲染为可读一行；6 个预算用例 + `__kwdefaults__` 断言阈值即模块常量 |
| 7 | LLM 通道与 purpose session 隔离延续；无 key 环境离线全绿 | **达成** | 未改 `resolve_digest_channel`/`digest_session`/`MAX_SUMMARY_TOKENS`/`_live` 接缝；`test_digest_purpose_session_is_isolated_and_env_overridable`、`test_digest_live_seam_omits_temperature_and_raises_max_tokens` 原样通过 |
| 8 | 新增/修改测试覆盖四节/统计/缓存/预算；全量 pytest 绿 | **达成** | 新增 26 + 20 = **46** 个用例；`pytest -p no:warnings` **1096 passed / 0 failed**（基线 1048 → +48：46 新 + 2 新增 API 用例；node 套件由 pytest 包装，含在这 1096 内） |

残留（诚实标注）：见 §6。

---

## §1 生成链形状（新）

```
records ──▶ documents_in_range ──▶ apply_material_budget（纯）
                                     ├─ documents（≤MAX_DOCS，含 inbox_reasons/content_hash）
                                     └─ budget report（kept/omitted/guaranteed/per_topic_kept）
          ──▶ compute_stats（纯：计数/成功率/Inbox/连续体）
          ──▶ select_highlights（纯：重点标签 → 更长 → 更新）
          ──▶ 材料分区：organized（有 主题/标签）/ pending（无标签或 explicit/低置信）
          ──▶ section_fingerprints（topics / pending，各自材料的 sha256）

缓存阶梯：
  ① 整报 fingerprint 命中        → 0 调用（A2 语义不变，API 返回 cached=True）
  ② 节级 fingerprint 命中        → 该节复用旧正文（0 调用）；其余节合成一次调用
  ③ 都未命中                     → 1 次调用，返回分节 JSON，schema 校验
  force=True 绕过 ①②③（整报 + 节级缓存全绕）

输出：markdown = # 本周小结 + 四节（概览/主题脉络/重点文档摘录/待整理与连续体进展）+ ## 来源
      meta.json = 旧字段 + sections / section_fingerprints / section_details / stats / budget / llm_mode
```

## §2 关键设计决策（请评审重点看这几条）

1. **骨架由数据决定，不由模型决定**：`SECTION_DEFS` 是唯一顺序来源；模型只输出「分节 JSON」
   （`{"sections": {"topics": {...}, "pending": {...}}}`），fence/裸 JSON/顶层直挂三种容错，
   未知 document id 一律丢弃。模型只被请求缺失的节（节缓存命中时 prompt 里不出现该节键）。
2. **概览/摘录 100% 确定性**：模型从不产出统计数字，也读不到「概览」这个节（prompt 不含 `"overview"`）。
3. **材料分区（`_is_pending`）**：待整理材料 = 完全无 主题/标签 的文档，或带 `explicit`/`low_confidence`
   标记者；其余进主题脉络材料。理由：Inbox 投影对「有主题无标签」会给 `no_tag`，若照搬会让只用主题
   的库出现空「主题脉络」。**Inbox 统计口径仍是原样投影**（`inbox_in_range`/`inbox_reason_counts`），
   两者差异在 §6-R2 说明。
4. **指纹内容选择**：整报指纹 = schema+`GENERATOR_VERSION`+范围+（id, version_id, content_hash）——
   所以 `GENERATOR_VERSION` 从 `digest-1` 提到 `digest-2` 后，**旧 digest 永不被复用**（A2 的 v1 meta 只能
   通过 `find_cached` 精确命中它自己的旧指纹，有测试）。
   节级指纹只看 `content_hash`（**不含 version_id**），并带 `SECTION_PROMPT_VERSION`——这正是
   「版本号变了正文没变 → 该节仍命中」这一加分能力的来源。空材料节指纹为 `""`，永不命中。
5. **回退规则**：模型回复不是分节 JSON 时（`llm_mode="text-fallback"`）全体散文下沉一级标题后落在
   **首个被请求的节**，来源取当次材料全集；其余节仍保留确定性内容（待整理仍有统计块）。
   `_demote_headings` 保证 `##`→`###`，不会打乱骨架层级。
6. **`llm_calls` 语义变更**：meta 里的 `llm_calls` 现在是**实际调用次数**（节缓存全命中时为 0），
   不再是恒为 1；`llm_mode ∈ {json, text-fallback, section-cache}` 记录本次是哪种路径。
7. **节缓存只存「模型散文」**：`<id>.sections.json` 只放 narrative 正文（不含概览/待整理统计），
   统计永远按当前库状态重算——这是 review 时值得盯的一处（初版曾把合成后的整节存下来，
   复用时统计块被复制两遍，已修，`test_section_cache_reuses_the_unchanged_section` 会抓）。
8. **`SCHEMA_VERSION` 1→2**，meta 新增键全部是加法；`load_digest` 多返回 `sections`（旧 meta → `[]`），
   现有调用方（CLI/webapp/telemetry）不需要改。
9. **预算算法**：基线取最新 `max_docs` 篇；每个 主题/标签 标签保底最新 `TOPIC_FLOOR` 篇；超出部分
   从「最老且未被保底」的文档开始丢；保底集合本身超预算时按时间截取。返回值按 (date, id) 升序，
   纯函数、不改输入、与输入顺序无关（有置换测试）。
10. **摘录预算**：`document_excerpt` 保证 `len(out) ≤ HIGHLIGHT_CHARS`（含省略号），中英文一致；
    选择规则 = 重点/important/key 标签优先 → 正文更长 → 更新 → id 升序。

## §3 证据（可复跑命令与结果）

离线（全部注入 golden planner，不触网）：

```
.venv/bin/python -m pytest -p no:warnings -o addopts="--strict-markers -q"
→ 1096 passed in 132.52s

.venv/bin/python -m pytest -p no:warnings -q \
    tests/test_digest_structure.py tests/test_digest_budget.py tests/test_weekly_digest.py
→ 79 passed（26 + 20 + 33）
```

- 新增 golden：`tests/golden/weekly-digest.sections.json`（分节 JSON 回复，含一个不存在的 id 用于验证丢弃）；
  旧 `weekly-digest.golden.md` 继续作为 **fallback 路径** golden 使用（既有全链用例现在跑的就是它）。
- 新增用例分布：`test_digest_structure.py` 26（骨架/来源/校验/meta 兼容/节缓存/回退/摘录）、
  `test_digest_budget.py` 20（预算 8 + 统计 8 + 摘录 4）。
- `tests/test_weekly_digest.py` 改动：`render_digest_markdown` 换新签名（3 处断言）、全链用例增加四节断言、
  新增 2 个 API 契约用例（W1→W2 meta；旧 meta 服务不炸）。既有 AC 断言（零调用缓存、force、会话隔离、
  telemetry 合并、DOM 契约、CLI）一条没删。

live（可选，1 次，kimi 文本通道；**只报结构，未打印/导出任何模型输出与密钥**）：

```
通道：provider=kimi，purpose=classify（graph2note.llm_settings 解析出的文本通道）
脚本：/tmp/spw-w1-live-smoke.py（写入仅 /tmp 临时 storage，跑完删除；仓库无产物）
结果：status=ok llm_calls=1 mode=json
      section overview: source_ids=3 detail=deterministic
      section topics:   source_ids=2 detail=model
      section highlights: source_ids=3 detail=deterministic
      section pending:  source_ids=1 detail=model
      four_sections_in_markdown=True  source_footer=True
      usage 含 prompt/completion/reasoning/total tokens
```

> 复跑注意：live 脚本必须让 worktree 的 `graph2note` 先于 site-packages 命中
> （`python -c` 从 worktree 跑，或显式 `PYTHONPATH=<worktree>`；直接 `python /tmp/x.py`
> 会把 /tmp 放进 `sys.path[0]`，可能命中已安装旧包——首次跑就踩到过，报 mode=None）。

## §4 与 W2 的契约（照 SPEC §3）

- `meta.json`：`sections: [{key, title, source_document_ids}]`，key 固定
  `overview / topics / highlights / pending`，顺序即展示顺序；外加
  `section_details{key:{generated_by,chars}}`、`stats{...}`、`budget{...}`、`llm_mode`（W2 可选用）。
- `GET /api/digests/{id}` 与 `POST /api/digests` 都原样带 `meta.sections`；POST 额外返回扁平
  `sections` 列表（同一契约）。旧 digest（无 `sections`）由 W2 回退整篇渲染即可，W1 侧已保证不炸。
- W1 **不动** dashboard.js/index.html；markdown 仍是完整四节，W2 不做分节 UI 时也能直接展示。

## §5 测试清单（新增/修改）

| 文件 | 变化 | 覆盖 |
|---|---|---|
| `tests/test_digest_structure.py` | 新增（26） | 骨架顺序、四节 Markdown、统计不经 LLM、来源校验、meta 持久化/重载、旧 meta/list、节级缓存三类命中、fallback、错误路径、摘录预算、材料分区 |
| `tests/test_digest_budget.py` | 新增（20） | 预算取舍 8（无压力/纯时间/保底/置换/保底超预算/0 预算/多标签/阈值即常量）+ 统计 8 + 摘录 4 |
| `tests/test_weekly_digest.py` | 修改 | 渲染器新签名、全链四节断言、+2 API 契约用例 |
| `tests/taxonomy.py` | +2 行 | `test_digest_structure` / `test_digest_budget` → `notes` |
| `tests/golden/weekly-digest.sections.json` | 新增 | 分节 JSON golden |

## §6 残留 / 风险（供 reviewer 决策）

- **R1 连续体「待确认对」在生产里基本恒为 0**：`detect_continuity(include_suggested=True)` 的 suggested
  层需要 IR（`document_ir`），而 webapp/CLI 传进 digest 的 records 来自 `store.get_document`（不带
  `ir_json`），所以只有 significant（同 PDF 相邻页）能计到数；同时库规模 > `CONTINUITY_SUGGESTED_MAX_DOCS(200)`
  时按设计只算 significant 层。统计口径是纯函数且可测，但「待确认 N 对」在真实库里偏保守。
  若要修，需 W1 外（改 webapp 传参或 store 侧 enrich），本轮按「不越领地」不动。
- **R2 区块口径差异**：`stats.inbox_*` 用 Inbox 原样投影（含仅缺标签），材料分区用「无标签才算待整理」。
  即 `inbox_in_range` 可能大于「进待整理材料的篇数」。这是有意为之（§2-3），但 W2 若要把两者并排展示，
  需知道它们不是同一个数。
- **R3 meta 变大**：新增 `stats`（含 topics/tags 列表）/`budget`/`sections`，库大时 `GET /api/digests`
  会把全部 meta 一起返回。单条增量约 KB 级、30 篇材料下 < 4KB；如需精简可后续在 list 端点裁剪。
- **R4 模型 JSON 质量**：live 1 次返回合法 JSON，但长材料（60 篇 × 2000 字）下是否稳定未压测。
  fallback 路径保证「不炸且仍有四节」，但散文会整体落在主题脉络节。
- **R5 `elapsed`**：`llm_calls=0` 时记为 0.0（没有模型耗时），语义与旧版（1 次调用总耗时）不同。
- **R6 未被指标覆盖**：`render_digest_markdown` 的行级排版（空节占位 `_（本节没有可归纳的内容）_`）
  只按结构断言，没有视觉验收——W1 未启动浏览器（dashboard 属 W2 领地）。

## §7 评审建议的最小验证路径

```bash
cd <worktree>
.venv/bin/python -m pytest -p no:warnings -q tests/test_digest_structure.py \
    tests/test_digest_budget.py tests/test_weekly_digest.py     # 79 passed
.venv/bin/python -m pytest -p no:warnings                        # 1096 passed
# 抽取式验收：随机构造库 → 概览数字 vs compute_stats；同库重复请求 0 调用；
#              改一篇材料 → llm_calls=1 且另一节 generated_by=section-cache
```
