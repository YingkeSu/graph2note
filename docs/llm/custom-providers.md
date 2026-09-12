# 自定义 LLM 供应商接入（任意 OpenAI 兼容端点）

> 用途：在固定内置注册表（Kimi / DeepSeek / opencode go）之外，允许用户添加**任意 OpenAI
> 兼容**供应商，并按用途（解析视觉 / IR 文本 / 图形提取 / 分类归纳）指派。形式对齐 GitHub
> 主流 agent 项目（OpenCode、Cherry Studio、LobeChat 等）的「一组通用字段，不锁定厂商」。
> 相关代码：`graph2note/llm_settings.py`（存储与校验）、`eval/gateway.py`（传输层）。

## 1. 字段含义

设置页「LLM 设置 → 自定义供应商」区（或 `POST /api/llm/providers`）填写：

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` 名称 | 是 | 显示名，也是自动生成的供应商 id 来源（如「DeepSeek 兼容」→ `custom-deepseek`） |
| `base_url` Base URL | 是 | 供应商 API 根，必须是 `http(s)://host[/path]`；末尾 `/` 会被规范化 |
| `api_key` API Key | 否 | Bearer 凭证。**只写不读**：GET/界面只回显「已设置/未设置」，明文不返回 |
| `models` 模型列表 | 是 | 手填（每行一个或用逗号分隔）；也可点「拉取模型」从 `{base_url}/models` 获取 |

请求协议固定为 **OpenAI Chat Completions**：

```
POST {base_url}/chat/completions
Authorization: Bearer <api_key>
Content-Type: application/json

{"model": "<模型名原样透传>", "messages": [...], "max_tokens": ...}
```

**模型名原样透传**：自定义供应商不套用 Kimi/DeepSeek 的 `DEEPSEEK_MODEL_MAP`。你在模型列表里
填什么，请求体 `model` 就是什么（内置 DeepSeek 通道才会把 `glm-5.3-flash` 翻译成官方视觉别名）。

## 2. 常见兼容端点示例

| 厂商 / 服务 | Base URL | 示例模型 | 备注 |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` / `gpt-4o-mini` | 标准 Chat Completions |
| DeepSeek 官方 | `https://api.deepseek.com` | `deepseek-chat` / `deepseek-reasoner` | OpenAI 兼容（也可直接用内置 deepseek 通道） |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o` / `anthropic/claude-3.5-sonnet` | 模型名含 `/`，原样透传 |
| Moonshot / Kimi | `https://api.moonshot.cn/v1` | `kimi-k2.6` | 与内置 Kimi 通道同源 |
| SiliconFlow 等中转 | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` | 各家中转一般兼容 |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `llama3.1` / `qwen2.5` | 无 key 可留空；`/models` 返回 `{"models":[{"name":...}]}` |
| 本地 vLLM / LM Studio | `http://127.0.0.1:8000/v1` | 部署时的模型 id | 同上 |

> 视觉（解析）用途要求所选模型本身支持图片输入（`image_url` data URL）。纯文本模型只能用于
> 「IR 文本 / 分类归纳」，或作为 PDF 问答文本通道。

## 3. 按用途指派（channels）

新增供应商后会出现在「按用途选择」的供应商下拉里。每个用途（`parse_visual` / `ir_text` /
`diagram` / `classify`）独立选供应商 + 模型，落到 `channels` 结构，运行时由
`graph2note.llm_settings.resolve_channel(purpose)` 读取：

- 视觉（解析 / 图形提取）：`graph2note.vlm.call_ir` → 解析视觉与图形提取通道。
- 文本（IR 文本 / 分类 / PDF 问答）：`graph2note.route_b`、`graph2note.notes.llm`、
  `graph2note.pdfqa` 走同一 `post_gateway` choke point。

**删除 / 改坏模型列表时的回退**：删除供应商，或把某用途正在用的模型从列表里移除，会自动把该用途
指派回退到内置默认（当前 `GRAPH2NOTE_GATEWAY` 的对应默认模型），并在界面/接口返回可读提示
（`notice` + `reverted`），不会留下悬空指派。

## 4. 健康检查

「检测可用性」对自定义供应商同样生效：发一次小 `max_tokens` 探测（沿 `probe_channel` 模式）。
结果状态：

- `available`：端点 200 且返回合法响应。
- `auth_failed`：401/403（key 错误或过期）。
- `missing_credentials`：条目未填 API Key。
- `request_failed`：网络/结构/配置错误，`detail` 为可读原因。

探测与「拉取模型」的错误信息**从不包含 key**（见 §5）。

## 5. Key 的本机存储口径（安全）

- 供应商条目（含明文 key）写入 `<storage>/llm-settings.json`（由 `graph2note.config` 解析，
  默认 `~/Library/Application Support/Graph2Note/storage/llm-settings.json`，可用
  `GRAPH2NOTE_STORAGE` / `GRAPH2NOTE_SETTINGS_FILE` 覆盖）。storage 目录已 gitignore；
  写文件时 `chmod 600`（属主可读），与仓库根 `.env` 同级安全假设。
- **只写不读**：`GET /api/llm/settings` 与界面回显只有 `credential_configured` 布尔值，
  明文 key 不离开本机存储。更新条目时 `api_key` 留空表示「保持原值」。
- **日志/遥测零 key**：传输层错误体里的 key 会被脱敏为 `[redacted]`；探测详情在返回前统一
  扫描进程内所有已知凭证并脱敏（跨供应商也不会互相泄露）。遥测只记录 provider/model 与用量。
- 模型名、Base URL 会出现在界面与设置文件里，但不属于机密。

## 6. 接口一览（本地 Web API）

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/llm/settings` | 快照：用途、供应商（内置 + 自定义）、channels |
| `PUT/PATCH` | `/api/llm/settings` | 更新用途指派 |
| `POST` | `/api/llm/providers` | 新建自定义供应商 |
| `PUT/PATCH` | `/api/llm/providers/{id}` | 修改（key 留空保持原值） |
| `DELETE` | `/api/llm/providers/{id}` | 删除并把相关用途回退默认 |
| `POST` | `/api/llm/providers/{id}/models` | 从 `{base_url}/models` 拉取模型清单 |
| `GET/POST` | `/api/llm/health` | 检测各用途通道可用性 |

非法的 Base URL、空模型列表、与内置 id 冲突的 id、未知供应商一律返回 `422` + 可读 `detail`。

## 7. 冒烟验证（可选，手动）

自定义供应商是真实端点时，可用一次最小调用确认链路（`graph2note.llm_settings.probe_channel`
或界面「检测可用性」）。CI 与测试套件一律 stub HTTP，**不做真实网络调用**；真实冒烟记录见
`.scratch/usable-product-iteration/handoffs/A3-custom-llm-provider.md`。
