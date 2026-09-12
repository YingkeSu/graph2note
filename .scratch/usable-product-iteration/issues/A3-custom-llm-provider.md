# A3：自定义 LLM API 接入（任意 OpenAI 兼容供应商）

Status: merged
Labels: track-llm

## What to build

覆盖维护者需求「增加 LLM API 自主选择功能；形式参考 GitHub 各 agent 项目的通用做法」。在现有固定供应商注册表（Kimi/DeepSeek）之外，允许用户添加**任意 OpenAI 兼容**的自定义供应商，并按用途（解析/分类/问答等）指派。

形式对齐 GitHub 主流 agent 项目（OpenCode、Cherry Studio、LobeChat 等）的自定义供应商模式——一组通用字段，不锁定厂商：

- **供应商条目**：`名称` + `Base URL` + `API Key` + `模型列表`（手填为主；可选加分：`/models` 拉取）。API 风格固定 OpenAI Chat Completions（`{base_url}/chat/completions` + Bearer Key），模型名原样透传（不走 `map_model` 改写）。
- **配置 CRUD**：设置页新增「自定义供应商」区（现行 LLM 设置视图内），增删改查；**API Key 只写不读**——GET/界面回显仅返回"已设置/未设置"，明文不离开本机存储。
- **存储与安全**：条目（含 key）落 `llm-settings.json`（在 storage 内，已 gitignore，本机明文可接受——与 `.env` 同级安全假设，文档明示）；日志与遥测永不记录 key。
- **网关路由**：`eval/gateway.py` 的 `gateway_config`/`chat_completions_url`/`load_api_key` 支持自定义供应商解析；视觉（解析）与文本（分类/A2 小结/PDF 问答）两类调用均可路由到自定义端点；按用途指派沿用现有 channels 结构（`resolve_channel(purpose)`）。
- **健康检查**：现有「检测可用性」对自定义供应商生效（小 `max_tokens` 探测，沿 `probe_channel` 模式）。
- **文档**：`docs/llm/` 增自定义供应商接入说明（字段含义、常见兼容端点示例、key 的本机存储口径）。

## Acceptance criteria

- [ ] 添加自定义供应商（名称/Base URL/Key/模型）后，其出现在供应商列表，可为每个用途指派；指派后 `resolve_channel` 返回正确端点与模型（单测）。
- [ ] 请求组装正确：URL = `{base_url}/chat/completions`、Bearer 鉴权、模型名透传、不套用 Kimi/DeepSeek 的 map_model（stub HTTP 断言请求体与头）。
- [ ] API Key 安全：GET 设置与 UI 回显只含"已设置"状态，无明文；日志/遥测扫描无 key（沿密钥检查验收惯例）。
- [ ] 健康探测对自定义供应商可用（stub 200/401 两路），失败信息可读。
- [ ] 视觉 + 文本两条调用路径均能路由自定义供应商（stub 网关级测试，CI 无真实调用）；真实端点冒烟 1 次记 handoff（预算 ≤2 次调用，模型任选）。
- [ ] 删除供应商时其用途指派回退默认并提示；既有 llm_settings/gateway 测试全绿。

## Blocked by

None - can start immediately
（领地提示：设置视图入口会被 U1 迁到侧栏——U1 承诺行为保持；本 issue 以现行设置视图交付）
