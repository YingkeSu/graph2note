# OpenCode Go 网关参考（LLM 接入文档）

> 用途：本项目（Manuscript Compiler）Spike 阶段及 MVP 的 LLM 调用通道。
> 检索与验证日期：2026-09-08。模型清单来自官方文档 + `/v1/models` 实测交叉验证。
> 认证密钥：仓库根目录 `.env` 中的 `OPENCODE_API_KEY`（已加入 `.gitignore`，勿提交、勿写入任何文档或代码）。

## 1. 端点

Base：`https://opencode.ai/zen/go/v1`，三个 API 面：

| 路径 | 风格 | 适用 |
|---|---|---|
| `/v1/chat/completions` | OpenAI 兼容 | **本项目主用**（视觉模型在此端点） |
| `/v1/responses` | OpenAI Responses | grok / gpt / muse 系列 |
| `/v1/messages` | Anthropic Messages | minimax / qwen 系列 |
| `/v1/models` | 模型清单 | `GET`，返回全部可用模型 |

## 2. 认证（实测确认）

- Header：`Authorization: Bearer $OPENCODE_API_KEY`
- **必须**携带 `x-opencode-session: <稳定会话ID>`（如 `graph2note-parse-01`）。缺失会报错：
  `MissingSessionID: Request is missing x-opencode-session and cannot be routed efficiently.`
  同一会话/同图重试时保持同一 session ID，有利于路由与 prompt 缓存。
- 客户端应设置自己的 User-Agent 标识。

### 2.1 会话隔离使用规范（issue 12 风控）

**现象（并发争用）**：历史默认 parse 与 eval 共用同一已验证会话 `graph2note-spike-01`。当
评估批次（worker）× 产品解析 × 交叉验证并发跑时，共享会话退化，VLM 对真实扫描页返回极短
完成（「本页全黑/空白」文案、空 IR），即使 prompt 正确。这是**服务层按会话路由/缓存的争用**，
而非提示词问题——任意 prompt 在退化会话下都拿不到正文（见 issue 12 风控登记）。

**隔离策略**：每个**用途**持有独立、已直出验证的稳定 session id，互不争用；env 可覆盖：

| 用途 | 默认 session | 覆盖 env | 消费者 |
|---|---|---|---|
| parse（产品解析） | `graph2note-parse-01` | `GRAPH2NOTE_SESSION_PARSE` | vlm.resolve_session / RouteARouter |
| eval（评估 harness） | `graph2note-eval-01` | `GRAPH2NOTE_SESSION_EVAL` | eval/gateway.resolve_sessions |
| verify（交叉验证） | `graph2note-verify-01-<model>` | `GRAPH2NOTE_SESSION_VERIFY` | detect/verify engine |

- 解析优先级（`eval.gateway.resolve_session_for(purpose, model)`，vlm 委托 parse 用途）：
  `GRAPH2NOTE_SESSION_<PURPOSE>` > 历史 `GRAPH2NOTE_OPENCODE_SESSION` / `OPENCODE_SESSION` > 用途默认。
- 历史还原：`GRAPH2NOTE_SESSION_PARSE=graph2note-parse-route-a`（旧产品默认）或
  `GRAPH2NOTE_SESSION_*=graph2note-spike-01` 可经 env 还原旧会话（不改变默认）。
- **每个 session 首次使用前应做直出验证**（`eval.gateway.validate_session_direct(purpose)`）：发一次极小
  探针调用（2×2 图 + 64 token），检查 content 非空且 `reasoning_tokens <= 800`（阈值
  `RUNWAY_REASONING_TOKENS`）；非直出（推理路由烧预算）应换会话或升预算。结果进程级缓存。
- 生产首调：设 `GRAPH2NOTE_VALIDATE_SESSIONS=1` 时于首次解析触发直出验证（默认关，避免每进程多花
  一次调用）；验证脚本 `scripts/validate_sessions.py` 可对三个用途各验一次（预算 3 次）。


## 3. 视觉能力（对本项目关键）

已实测确认的视觉模型共两个（均可处理图片输入）：

- `glm-5.3-flash` —— 官方文档未标注视觉能力，2026-09-08 实测通过。
- `deepseek-v4-flash-vision-exp` —— 官方标注 experimental 的视觉模型。

- 图片以 OpenAI 格式 `image_url`（base64 data URL）传入 `chat/completions`。
- 图片按尺寸折算为 token，与文本一起按输入 token 计费。
- **实测（2026-09-08，本仓库 `test-images/` 手稿）**：
  - `deepseek-v4-flash-vision-exp` × 2 张：均正确读取——判断无旋转、准确概括主题（Agent 编排架构 / 输入层→解析层→格式化输出与 LLM/OCR 路由）。
  - `glm-5.3-flash` × `02-digitize-pipeline.jpg`：正确判断无旋转，主题概括准确完整（输入→LLM/OCR 解析→Markdown/CSS 模板→编译 PDF）。
  - 结论：两个视觉模型的中文手稿链路均可用；识别质量对比待 Spike 1 用 30–50 张评估集定量验证。

### 实测注意事项（踩坑记录）

1. 两个视觉模型均输出 `reasoning_content`（思考过程），**思考 token 消耗 `max_tokens` 预算**。`max_tokens=200` 时思考未完成即被截断（`finish_reason: length`），正文为空。**`max_tokens` 统一设 10000**（维护者确认；实测一次完整回答的思考消耗约 280–430 token，10k 确保长文档输出不被截断）。
2. 最终答案在 `message.content`，思考过程在 `message.reasoning_content`，解析时取前者。

### 最小可用示例

```bash
source .env
IMG=$(base64 -i test-images/01-requirements-arch.jpg | tr -d '\n')
curl -s "https://opencode.ai/zen/go/v1/chat/completions" \
  -H "Authorization: Bearer $OPENCODE_API_KEY" \
  -H "Content-Type: application/json" \
  -H "x-opencode-session: graph2note-spike-01" \
  -d @- <<EOF | python3 -c "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
{"model":"deepseek-v4-flash-vision-exp","max_tokens":10000,
 "messages":[{"role":"user","content":[
   {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,$IMG"}},
   {"type":"text","text":"把这一页手稿转成 Markdown。"}]}]}
EOF
```

## 4. 模型清单（2026-09-08 实测 `/v1/models`，共 36 个）

**视觉（可处理图片，已实测）**：`glm-5.3-flash`、`deepseek-v4-flash-vision-exp`

**chat/completions 端点**：`glm-5.3`, `glm-5.3-flash`, `glm-5.2`, `glm-5.1`, `glm-5`, `kimi-k3`, `kimi-k2.7-code`, `kimi-k2.6`, `kimi-k2.5`, `longcat-2.0`, `deepseek-v4-pro`, `deepseek-v4-flash`, `mimo-v2.5-pro`, `mimo-v2.5`, `mimo-v2-pro`, `mimo-v2-omni`, `hy4-preview`, `hy3`, `hy3-preview`, `omen-alpha`

**responses 端点**：`grok-4.6`, `grok-4.5`, `gpt-5.6-luna`, `muse-spark-1.3-contributor`, `muse-spark-1.2-contributor`

**messages 端点**：`minimax-m3`, `minimax-m2.7`, `minimax-m2.5`, `qwen3.8-max`, `qwen3.8-flash`, `qwen3.7-max`, `qwen3.7-plus`, `qwen3.6-plus`, `qwen3.5-plus`

> 模型清单会变化；用 `/v1/models` 实时查询为准。无视觉能力的文本模型可用于 Route B 的「OCR → LLM 结构化」中的 LLM 环节。

## 5. 配额与计费

- 订阅 $10/月；额度以美元值计：5 小时 $12 / 每周 $30 / 每月 $60（约为订阅价 6 倍使用量）。
- 单模型月度额度示例：`deepseek-v4-flash-vision-exp`、`glm-5.3`、`kimi-k3`、`grok-4.6` 等为 $15；`qwen3.8-flash`、`deepseek-v4-flash` 等为 $30；多数其余 $60；`omen-alpha` $100。
- 可开启「Use balance」在超额后回落到 Zen 余额。
- DeepSeek 系列分时段计价（UTC 工作日 01:00–04:00、06:00–10:00 为高峰）。
- 实测响应中 `cost` 字段为 `"0"`（订阅内不计次费）。

## 6. 隐私

- 大多数模型：不用于训练，0 天保留。例外：`grok-4.6` / `gpt-5.6-luna` 日志保留最长 30 天；**`muse-spark-*-contributor` 会用你的输入训练模型**——本项目（个人手稿）禁止使用 muse 系列。
- 个人自用定位下隐私负担低，但仍以上述为选择约束。

## 7. 来源

- 官方文档：https://opencode.ai/docs/go/ （端点、模型、配额、隐私）
- 模型发现端点说明：https://opencode.ai/docs/providers/
- 实测记录：本仓库 Spike 冒烟测试（2026-09-08，两张 `test-images/` 手稿）
