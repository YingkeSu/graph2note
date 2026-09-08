# 网关会话隔离：按用途隔离稳定直出 session

Status: merged

## Parent

[PRD](../PRD.md)（主链路质量 / 服务层加固）；来源：issue 12 验收后协调器指派（防共享会话争用复发）。
证据链：issue 12 风控登记（parse/eval 共用 `graph2note-spike-01` 时并发批次互相挤占，VLM 退化返短）。

## What to build

按用途隔离稳定会话：parse / eval / verify 各自持有独立、已验证直出的 `x-opencode-session`
（如 `graph2note-parse-* / graph2note-eval-* / graph2note-verify-*`），env 可覆盖；启动/首次调用
做直出验证（reasoning_tokens 检查）；统一配置收敛到 vlm/gateway 层；写一份会话使用规范进
`docs/llm/opencode-go.md`（追加一节，注明并发争用现象与隔离策略）。

## Acceptance criteria

- [x] 按用途（parse/eval/verify）各持独立已验证直出 session，env（`GRAPH2NOTE_SESSION_<PURPOSE>`）可覆盖
- [x] 启动/首次调用做直出验证（reasoning_tokens 检查；`GRAPH2NOTE_VALIDATE_SESSIONS` 开关）
- [x] `resolve_session_for` 配置统一收敛在 eval/gateway，vlm（parse）/router/verify 委托
- [x] `docs/llm/opencode-go.md` 追加「会话隔离」一节（争用现象 + 隔离表 + env + 验证）
- [x] 离线测试覆盖配置解析、session 选择、验证判据（`pytest tests/` = 236 passed, 2 skipped）
- [x] live 验证 ≤3 次（每用途一次）：三 session 全部 status=ok、reasoning ≤63、直出可用

## Blocked by

None.

## 实施记录

见 `reports/session-isolation/report.md`（实现 / live 验证 / 测试 / 风险）与
`handoffs/14-gateway-session-isolation.md`。