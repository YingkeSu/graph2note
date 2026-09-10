# DeepSeek 官方 API 参考（LLM 接入文档 · 备援通道）

> 用途：本项目（Manuscript Compiler）的 LLM 调用**备援通道**。opencode go 网关 2026-09-10 起
> 暂不可用，经 `GRAPH2NOTE_GATEWAY=deepseek` 切换到本通道（`.env` 已配置；恢复后删除该行即回
> opencode 默认）。主通道文档见 [opencode-go.md](opencode-go.md)。
> 检索与验证日期：2026-09-10。模型清单来自 `/models` 实测 + 官方文档交叉验证。
> 认证密钥：仓库根目录 `.env` 中的 `DEEPSEEK_API_KEY`（已 gitignore，勿提交、勿写入代码）。

## 1. 端点

Base：`https://api.deepseek.com`（OpenAI 兼容），本项目主用 `/chat/completions`。
另有 Anthropic 兼容面（`/anthropic`）与 Responses API，本项目不使用。

- 认证：`Authorization: Bearer $DEEPSEEK_API_KEY`
- **无需 session 头**（`x-opencode-session` 是 opencode 专属；本通道不携带）。
  网关层 `post_gateway` 已按 `GRAPH2NOTE_GATEWAY` 自动处理端点/认证/session 头。
- 客户端保留自己的 User-Agent。

## 2. 模型清单（2026-09-10 实测 `/models`）

| 模型 | 视觉 | 用途（本项目） |
|---|---|---|
| `deepseek-flash` | **是**（本体即多模态） | 文本侧默认（IR stage-2 等价物 `deepseek-v4-flash` 的映射目标） |
| `deepseek-v4-flash-vision-exp` | 是 | **parse 视觉转录默认**（文档化视觉别名，响应 `model` 回显为 `deepseek-flash`，两者等价） |
| `deepseek-v4-pro` | 否（图片请求返回 400） | 备用文本模型 |

- 模型名映射（`eval.gateway.DEEPSEEK_MODEL_MAP`，单一 choke point 在 `post_gateway`）：
  `glm-5.3-flash → deepseek-v4-flash-vision-exp`；`deepseek-v4-flash → deepseek-flash`。
  调用方（parse/IR/diagram/verify/eval/gold_draft）继续用 opencode 时代模型名，无需改动。
- 错误模型名返回 400 并附完整支持清单（`The supported API model names are deepseek-flash,
  deepseek-v4-pro, ...`），可作为清单巡检。

## 3. 视觉输入（对本项目关键）

- 图片以 OpenAI 格式 `image_url`（base64 data URL）传入 `chat/completions` 的 **user 消息**
  （system/assistant 消息带图会 400）——与现有管线构造一致，无需改动。
- 计费口径：图片缩放至约 800×800 后折算 token，**每图上限约 384 token**（官方 Vision 指南）；
  与文本一起按输入 token 计费。
- 约束：JPEG/PNG/GIF/WebP；单图 ≤32 MiB（base64/URL）、请求体 ≤48 MiB、单边 ≤8192px；
  本管线发送前已降采样至最长边 1024，远低于上限。

### 实测记录（2026-09-10，`test-images/01-requirements-arch.jpg` 缩至 512px）

1. `deepseek-flash` 文本探针：正常直出（`finish=stop`），`usage` 齐全（见 §5）。
2. `deepseek-flash` 视觉调用：正确识别手稿左侧「方框+箭头流程图 / 右侧文字笔记」结构，
   中文概括准确——视觉链路可用。
3. `deepseek-v4-flash-vision-exp` 与 `deepseek-flash` 等价（别名回显），文档名与实测一致。

## 4. 响应形态（与 opencode 的差异）

- 最终答案在 `message.content`，思考在 `message.reasoning_content`——与 opencode 相同，
  现有解析逻辑不变。
- **思考 token 依旧消耗 `max_tokens` 预算**（实测视觉调用 reasoning 189 token），预算策略
  （首调 3500 / 升级 10000）沿用。
- 无 session 语义：重试策略中「换 session」在本通道退化为仅换参/换 prompt（`post_gateway`
  自动省略 session 头，重试无害）。
- 会话直出验证（`GRAPH2NOTE_VALIDATE_SESSIONS`）是 opencode 专属风控，本通道自动跳过。

## 5. 用量与计费

- `usage` 字段**完整回填**（opencode 时代常为 null）：`prompt_tokens` / `completion_tokens` /
  `total_tokens` / `completion_tokens_details.reasoning_tokens` / 缓存命中字段
  （`prompt_cache_hit_tokens` 等）——knowledge-workspace 的 token 统计在本通道天然有数据。
- 计价随官方价目（DeepSeek 系列分时段），实测响应不含 `cost` 字段；成本估计需本地价目表折算。

## 6. 切换方式

```bash
# .env（当前已配置）
GRAPH2NOTE_GATEWAY=deepseek   # 删除此行 = 回 opencode 默认
```

网关选择/映射的实现在 `eval/gateway.py`（`GATEWAYS` / `map_model` / `post_gateway`），
离线测试见 `tests/test_gateway_select.py`。

## 7. 来源

- 官方 Vision 指南：https://api-docs.deepseek.com/guides/vision/
- 官方发布公告（deepseek-v4-flash-vision-exp）：https://api-docs.deepseek.com/news/news260821/
- 实测记录：本仓库 2026-09-10 探针（models 列表 / 文本 / 视觉 / 别名等价 / 错误清单）
