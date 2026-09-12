# Handoff A3 — 自定义 LLM API 接入（任意 OpenAI 兼容供应商）

Branch: `dev/a3-custom-llm` · Issue: `.scratch/usable-product-iteration/issues/A3-custom-llm-provider.md` · Status → in-review

## 1. 一句话结论

在固定 Kimi/DeepSeek/opencode 注册表之外，交付了**任意 OpenAI 兼容自定义供应商**：名称 + Base URL +
只写不读的 API Key + 模型列表，落 `llm-settings.json`，可以在现行「LLM 设置」视图内增删改查，并按用途
（解析视觉 / IR 文本 / 图形提取 / 分类归纳）指派。请求组装固定 `{base_url}/chat/completions` + Bearer、
**模型名原样透传**（不走 `map_model`）；视觉与文本两条主链均路由到自定义端点；健康探测、`/models` 拉取、
删除回退、密钥零外泄（快照/日志/遥测/错误体）全部就位。34 项离线 stub 测试全绿，真实 DeepSeek 端点冒烟
2 次调用成功（预算 ≤2）。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/llm_settings.py` | 自定义供应商存储模型与 CRUD：`add_provider` / `update_provider` / `delete_provider` / `refresh_provider_models`；`provider_specs()`（传输层视图，含 key）；校验（Base URL / 模型列表 / id 冲突）；快照只暴露 `credential_configured`；删除与改模型导致失效指派→回退默认 + `notice`/`reverted`；文件 `chmod 600` |
| `eval/gateway.py` | `configure_custom_providers` / `custom_gateway_configs` / `available_providers`；`gateway_config`/`chat_completions_url`/`load_api_key`/`map_model` 支持自定义供应商；`fetch_provider_models`（`/models`，兼容 OpenAI `data[].id` 与 Ollama `models[].name`）；`_redact_secrets` 让传输层错误体不含 key |
| `graph2note/webapp.py` | `POST /api/llm/providers`、`PUT/PATCH/DELETE /api/llm/providers/{id}`、`POST /api/llm/providers/{id}/models`（`SettingsError` → 422） |
| `graph2note/webstatic/{index.html,app.js,style.css}` | 现行设置视图内新增「自定义供应商」区：表单（名称/Base URL/API Key/模型）、列表（编辑 / 拉取模型 / 删除）、Key 状态徽标 |
| `docs/llm/custom-providers.md`（新） | 字段含义、兼容端点示例（OpenAI/DeepSeek/OpenRouter/Kimi/中转/Ollama/vLLM）、按用途指派与回退、健康检查、key 本机存储口径、API 一览 |
| `docs/testing.md` | 模块→测试映射补登两个新测试文件 |
| `tests/test_custom_llm_provider.py`（新，28 项） | 存储 CRUD、请求组装、密钥安全、200/401 探测、视觉+文本路由、删除/改模型回退、`/models` |
| `tests/test_custom_llm_provider_api.py`（新，6 项） | Web API CRUD/校验/健康/静态 UI/`/models`（integration） |
| `tests/taxonomy.py` | 登记 `test_custom_llm_provider → config`、`test_custom_llm_provider_api → webapp`（含 integration 集） |

## 3. 关键决策

- **传输层不反向 import 设置层**：`eval/gateway` 是最底层的公共 choke point，若 import
  `graph2note.llm_settings` 会循环依赖。改为**进程级 source 回调**：`llm_settings` 在模块加载时
  `configure_custom_providers(lambda: runtime_settings_store().provider_specs())`，网关按需拉取合并视图。
  `GATEWAYS` 仍是内置供应商的唯一真相，自定义只读叠加，**内置 id 不可被覆盖**（`_normalize_custom_config`
  与 `_new_provider_id` 双重拒绝）。
- **模型名透传是硬保证**：自定义配置带 `custom: True`，`map_model` 对它直接原样返回；`post_gateway`
  里模型名映射只对内建生效。测试用 `glm-5.3-flash`（内建 deepseek 会映射为 `deepseek-v4-flash-vision-exp`）
  断言自定义通道请求体里仍是 `glm-5.3-flash`。
- **API Key 只写不读的三层防泄漏**：① `snapshot()`/`custom_providers` 只给 `credential_configured` 布尔；
  ② 更新时 `api_key` 缺省/空串=保持原值（不因编辑名称而清空）；③ `_safe_detail` 在返回探测详情前，把
  进程内**所有**已知凭证（内建 env/.env + 全部自定义条目）统一替换为 `[redacted]`——跨供应商也不互相
  泄露；`post_gateway`/`fetch_provider_models` 对 HTTP 错误体也做 key 脱敏。文件 `chmod 600`（与 `.env`
  同级安全假设，文档明示）。
- **失效指派显式回退而非静默丢弃**：`_read_channels` 对非法 stored channel 本来就会回落默认；为此删除/
  改模型时用「变更前 vs 变更后有效 channels」对比（`_diff_reverted`）识别「该用途原本指向被删/被改的
  供应商」，生成 `reverted` + 中文 `notice`，避免用户看到指派无声消失。
- **自定义条目的模型列表对所有用途共享**（扁平 `models`），因为协议固定 OpenAI Chat Completions、模型名
  透传；内建仍是 purpose-keyed `models`。`_models_from_config` 同时吃两种形状，快照里每用途 `capabilities`
  统一展开成同列表。
- **`/models` 拉取是可选加分的「显式动作」**：只在用户点「拉取模型」/调接口时触发，不隐式发请求；失败
  （401 等）返回 422 + 脱敏可读信息，不破坏已存模型列表。
- **设置视图落在现行入口**：开工时 main 只合到 S1（U1 未合），故在 `#nav-settings` → `#settings-zone` 内交付；
  新增块是 `settings-zone` 内的独立 section，U1 把入口迁到侧栏后行为不变（不依赖 `nav-settings` 的位置）。

## 4. AC 逐条证据

| AC | 证据（测试） |
|---|---|
| 1 添加后出现在列表、可指派、`resolve_channel` 正确 | `test_add_provider_appears_in_list_and_is_assignable`（列表末位为 `custom-deepseek`、`kind=custom`、每用途 capabilities、指派后 `resolve` 命中、`chat_completions_url` 正确）；`test_custom_channel_rejects_model_outside_provider_list` |
| 2 请求组装：URL/Bearer/模型透传/不套 map_model | `test_custom_request_url_bearer_and_verbatim_model`（stub `urlopen` 断言 URL=`https://api.deepseek.com/chat/completions`、`Bearer <key>`、无 session 头、body.model=`glm-5.3-flash`）；`test_text_gateway_request_assembly_for_custom`；`test_custom_provider_never_applies_deepseek_map_model`；`test_custom_base_url_trailing_slash_is_normalized` |
| 3 Key 安全：GET/UI 仅状态、日志/遥测零 key | `test_api_key_is_write_only_and_never_in_public_views`（快照无 key、本地文件有 key 且 0600、编辑保持/轮换）；`test_probe_details_and_transport_errors_are_redacted`（注入探测 + HTTP 500 回显 key 均 `[redacted]`、`caplog` 无 key）；`test_settings_and_telemetry_payloads_never_contain_the_key`（快照 + `normalize_telemetry` 扫描）；API 侧 `test_provider_crud_api_roundtrip_is_key_safe`（断言响应文本无 key） |
| 4 健康探测可用（stub 200/401）、失败可读 | `test_health_probe_custom_available`（200→`available`，URL/Bearer/max_tokens=1）；`test_health_probe_custom_auth_failure_is_readable`（401→`auth_failed`，detail 含 401、无 key）；`test_missing_custom_key_is_reported_without_network`（无 key→`missing_credentials` 且零 HTTP）；`test_probe_rejects_model_outside_provider_list` |
| 5 视觉+文本两路路由自定义 / 真实冒烟 1 次 | `test_visual_pipeline_routes_to_custom_provider`（`vlm.call_ir` 走自定义 provider，视觉+IR 两阶段 `provider` 均为自定义）；`test_text_classification_routes_to_custom_provider`（`notes.llm._gateway_text` 走自定义）；真实端点见 §5 |
| 6 删除回退默认并提示；既有测试全绿 | `test_delete_provider_reverts_assignments_with_notice`（`reverted` 两项、notice 含「回退默认」、resolve 已回退）；`test_update_provider_model_removal_reverts_stale_assignment`；`test_delete_provider_without_assignments_has_clean_notice`；`test_unknown_provider_operations_raise`；全量 550 passed（既有 llm_settings/gateway 全绿） |

## 5. 真实端点冒烟（预算使用记录）

**方案**：把本机 `.env`（主仓库 `/Users/suyingke/Programs/OHO/graph2note/.env`）里已有的 DeepSeek 官方
端点 + key 注册为「自定义供应商」走 custom 通道（DeepSeek 官方 API 为 OpenAI 兼容）。key 只从运行环境
读取，**未写入任何代码/测试/handoff，也未打印**。

- 环境：临时 `llm-settings.json`（`tempfile`，不触碰真实 storage），`configure_settings_path` 指向之。
- 调用 1（预算内）：`refresh_provider_models` → `GET https://api.deepseek.com/models`，发现
  `['deepseek-flash', 'deepseek-v4-pro']`。
- 调用 2（预算内）：指派 `classify → custom-deepseek/deepseek-flash` 后 `probe_channel`（`max_tokens=1`）
  → `status: available`，`detail: null`；`resolve_channel("classify")` 返回自定义端点条目。
- 安全断言：添加后快照 JSON 与探测结果 JSON 扫描均**不含 key**。
- **总预算使用 2 / 2 次**（一次 `/models` 发现 + 一次最小健康探测），无额外真实调用；CI 与测试套件全部
  stub HTTP、零真实网络。

## 6. 对外契约（给 U1 / 下游）

- **数据**：`llm-settings.json` `version: 2`，新增顶层 `custom_providers: [{id,name,base_url,api_key,models}]`；
  `channels` 结构与 v1 完全一致（无迁移成本，读旧文件缺 `custom_providers` 视为空）。
- **HTTP**：`GET /api/llm/settings` 增加 `custom_providers`（无 key）与 provider 的 `kind`/`base_url` 字段；
  新端点 `POST/PUT/DELETE /api/llm/providers[...]`。任何响应都只含 `credential_configured`。
- **网关**：`gateway_config(provider)`/`chat_completions_url`/`load_api_key`/`map_model` 对自定义 id 直接可用；
  下游按用途拿到的 `provider` 值就是自定义 id，传给 `post_gateway(provider=...)` 即可。
- **U1 提示**：自定义区是 `#settings-zone` 内独立 DOM 块（`#llm-custom-form` / `#llm-custom-list`），入口迁移
  只需保留 `renderLlmSettings()` 调用链，无需改本功能。

## 7. 如何运行

```bash
uv run pytest tests/test_custom_llm_provider.py tests/test_custom_llm_provider_api.py   # 34 passed
uv run pytest -m "config or webapp or eval"                                             # 相关模块
uv run pytest                                                                           # 550 passed
```

## 8. 未尽事项 / 建议

1. **id 生成**：默认 `custom-<name-slug>`，中文名会退化为 `custom-provider`（重复时加 `-2`）。UI 未暴露
   自定义 id 输入；如需可读 id，可在表单加一个可选「标识」字段（后端已支持显式 id）。
2. **Key 清除**：当前「留空 = 保持原值」，没有单独的「清除 key」动作；如需，可加 `clear_api_key: true`
   或直接删条目重建。
3. **`/models` 结果未做用途能力标注**：拉取回来的列表是纯 id，视觉/文本能力由用户自行判断（与
   OpenCode/Cherry Studio 一致）。若未来要自动探测视觉能力，可对每模型发一次极小图片探针（有调用成本）。
4. **读取粒度**：每次 `gateway_config` 都会读一次设置文件（read-through，无缓存）。单用户场景无感；若
   将来高频批量调用需要降开销，可在 gateway 侧加 mtime 缓存，但会牺牲「改文件即生效」的即时性。
5. **UI 交互只做了静态断言**：`app.js` 逻辑经 `node --check` 与静态关键字断言覆盖，未做浏览器端 E2E
   （项目无 GUI/E2E 测试惯例）；后端 API 已有 TestClient 集成测试兜底。

## 9. 相关文件

- 实现：`graph2note/llm_settings.py`、`eval/gateway.py`、`graph2note/webapp.py`、
  `graph2note/webstatic/{index.html,app.js,style.css}`
- 文档：`docs/llm/custom-providers.md`、`docs/testing.md`
- 测试：`tests/test_custom_llm_provider.py`、`tests/test_custom_llm_provider_api.py`、`tests/taxonomy.py`
- 上游：`.scratch/usable-product-iteration/ISSUE-DRAFT.md`、`issues/A3-custom-llm-provider.md`
- 相关既有：`docs/llm/{deepseek,opencode-go}.md`、`tests/test_llm_settings.py`、`tests/test_gateway_select.py`
