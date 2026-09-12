# A2：每周小结（范围内材料的周期性汇总）

Status: ready-for-agent
Labels: track-assistant

## What to build

覆盖维护者需求「根据选定范围内上传的材料整理每周小结」。给定时间范围，把范围内文档汇总成一份 Markdown 小结：写了什么、围绕哪些主题、有什么进展。按需生成、可重复、可追溯，不是定时任务。

- **范围选择**：本周 / 上周 / 自定义起止日。文档集合 = 有效时间（四时间戳优先级链）落在范围内的文档，无有效时间回退导入时间；PDF 来源文档同样纳入。空范围给出明确空态（"该范围内没有材料"），不生成空小结。
- **素材组装（确定性）**：范围内文档按有效时间排序，取标题 + 内容（超长截断，上限显式常量）+ 标签与主题；组装结果生成**指纹**（范围 + 文档 id 集合 + 内容版本）。
- **生成**：单次文本 LLM 调用（复用 `notes/llm.py::_gateway_text` 文本通道与 purpose session 隔离），prompt = 素材组装结果，输出 = Markdown 小结（结尾附来源清单：文档标题 + 链接 id）。**指纹缓存**：同指纹重复请求直接复用已生成结果，`force=true` 才重新调用（预算纪律：默认零增量调用）。
- **持久化**：`<storage>/digests/` 下落盘小结 md + meta json（范围、指纹、来源文档 id、模型、token/成本遥测）；列表可查历史。
- **入口**：
  - API：`POST /api/digests`（range, force?）与 `GET /api/digests`、`GET /api/digests/{id}`。
  - Web：数据看板新增「每周小结」区块（生成按钮 + 范围选择 + 历史列表 + 查看/复制）；小结查看复用现有 Markdown 渲染。
  - CLI（可选）：`graph2note digest --week this|last|--from --to [--force]`，便于离线验收。

## Acceptance criteria

- [ ] 范围→文档集合的映射有纯函数测试（含优先级链回退、空范围、PDF 来源文档）。
- [ ] 同指纹二次生成不触发新 LLM 调用（录制计数断言）；`force=true` 重新生成并落新版本。
- [ ] 生成走文本通道且 purpose session 隔离（不与解析/评估抢 session，沿既有网关纪律）；token 消费进遥测。
- [ ] 小结落盘含 meta（来源 id、指纹、模型、token）；重启后历史列表与内容可读。
- [ ] LLM 输出用录制 golden 离线测全链路（组装 → 调用 → 落盘 → API/UI 展示），CI 无真实调用；真实冒烟 1 次记 handoff（预算 1 次调用）。
- [ ] API 契约测试 + Web 区块 DOM 断言；空范围空态明确。

## Blocked by

None - can start immediately
（领地提示：看板区块与 U1/U5 无文件级强冲突，但 dashboard zone 若被 U1 重构需适配——调度按先到先做、后者适配协调）
