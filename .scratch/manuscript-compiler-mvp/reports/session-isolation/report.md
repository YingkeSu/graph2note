# 网关会话隔离（issue 14）：按用途隔离稳定直出 session

Status: in-review 　branch `dev/gateway-session-isolation`（自 origin/main 2227dd3）。

## 目标

加固网关，防止 issue 12 警示的**共享会话争用**：parse / eval / verify 原本共用已验证直出
session `graph2note-spike-01`（eval/gateway 默认、vlm 默认、verify 各自 id），并发批次会让
共享会话退化、VLM 返回极短「全黑页」/空 IR。本次为每一用途分配独立、已验证直出的
`x-opencode-session`，env 可覆盖，并在启动/首次调用时做 reasoning_tokens 直出验证。

## 实现（配置统一收敛在 eval/gateway.py，vlm 委托 parse 用途）

- `eval/gateway.py`：
  - `PURPOSES = ("parse","eval","verify")`、`DEFAULT_PURPOSE_SESSIONS`
    `{parse: graph2note-parse-01, eval: graph2note-eval-01, verify: graph2note-verify-01}`。
  - `resolve_session_for(purpose, model)`：`GRAPH2NOTE_SESSION_<PURPOSE>` > 历史
    `GRAPH2NOTE_OPENCODE_SESSION` / `OPENCODE_SESSION` > 用途默认；未知用途抛 ValueError。
  - `resolve_sessions(model)`：eval 主 session 走用途解析（不再硬编码 spike-01）。
  - `validate_session_direct(purpose, ...)`：进程级缓存的探针验证（2×2 PNG + 64 token），
    判据针对 issue-12 的「推理吃满预算致空」签名（无内容 且 reasoning >= max_tokens → 非直出）；
    低推理 + 内容字节 0（预算没留内容位）不算失败。
  - `session_validation_enabled()` / `maybe_validate_direct()`：`GRAPH2NOTE_VALIDATE_SESSIONS=1`
    时于首解析触发一次验证（默认关，避免每进程多花调用）。
- `graph2note/vlm.py`：`resolve_session(model)` 委托 parse 用途（默认 `graph2note-parse-01`），
  `STABLE_SESSION`/`VALIDATED_SESSION` 同步；`GRAPH2NOTE_VALIDATE_SESSIONS=1` 时首解析探测。
- `graph2note/router.py`：`RouteARouter(session=None)` 默认走 parse 用途解析。
- `graph2note/verify/engine.py`：verify 会话基座 `resolve_session_for("verify", model)` →
  `graph2note-verify-01-<model>`（保留每模型后缀；旧 `graph2note-crossval` 经 env 还原）。
- `scripts/validate_sessions.py`：三用途各验一次（预算 ≤3）。
- `docs/llm/opencode-go.md` §2.1：会话隔离使用规范（并发争用现象、隔离策略、env、验证）。

## 实时验证（预算 3 次，每用途一次）

来源：`scripts/validate_sessions.py` 实测（3 次 live 探针调用，glm-5.3-flash）：

| 用途 | session | status | reasoning_tokens | direct |
|---|---|---|---|---|
| parse | `graph2note-parse-01` | ok | None（即出正文） | **True** |
| eval | `graph2note-eval-01` | ok | 61 | **True** |
| verify | `graph2note-verify-01` | ok | 63 | **True** |

三会话均可达、status=ok、reasoning_tokens ≤63（≪ 阈值 800，低于 issue-12 的 3475/6000 退化量级）→
均判直出可用。持久证据：`reports/session-isolation/scripts/data/validate_sessions.json`。

## 离线测试（219 → 236 passed, 2 skipped；净增 19）

- `tests/test_gateway.py`：默认用途隔离且三者不同、env 覆盖优先级（用途 env > 历史 env > 默认）、
  未知用途抛错、大小写、探针验证判据（低推理空内容=direct、runaway=非 direct、error=非 direct、缓存单次触网）。
- `tests/test_session_isolation.py`（新增）：vlm parse 委托默认/env/历史 env、router 默认 None、
  verify 用途独立、三用途全隔离。

## 健康巡检（跑批前自检）

`scripts/validate_sessions.py --check` 提供极简健康巡检入口：逐用途探测并输出
`ok/degraded` 汇总；任一用途退化时以**非零退出码**结束，便于未来跑批前脚本化门控
（普通模式恒 0）。聚合逻辑 `eval.gateway.session_health(records)` 为纯函数，离线单测覆盖。
（本报告基线为 issue-14 合并时 236；追加健康巡检后全量 252 passed, 2 skipped。）

## 风险 / 说明

- 历史 `graph2note-spike-01` 保留为未知用途兜底只读常量，不再分配给具体用途；旧行为经
  `GRAPH2NOTE_SESSION_<PURPOSE>=graph2note-spike-01` 或 `OPENCODE_SESSION` env 还原。
- 探针验证判 `eval/verify` 直出依赖「低推理」信号；若日后换强推理路由，需提高
  `PROBE_MAX_TOKENS` 或阈值 `RUNWAY_REASONING_TOKENS` 复核。
- 会话 id 由客户端自选，网关按 id 路由/缓存；新默认 id 首段时间无 prompt 缓存（预热后即有），
  无正确性影响。