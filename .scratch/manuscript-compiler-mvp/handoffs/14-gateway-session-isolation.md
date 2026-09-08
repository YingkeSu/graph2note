# 网关会话隔离（GATEWAY SESSION ISOLATION）

Status: in-review 　branch `dev/gateway-session-isolation`（自 origin/main 2227dd3）
Primary consumer: coordinator / issue 08 Route B、worker 3/4（eval + verify 并发跑批无争用）。

## 为什么

issue 12 验收后交叉验证遗留一个服务层隐患：parse / eval / verify 三处默认/复用了同一已验证直出
会话 `graph2note-spike-01`。当评估批次（worker）× 产品解析 × 交叉验证并发时，共享会话退化，
VLM 返回极短「全黑/空白」完成、空 IR——即使 prompt 正确（issue 12 风控登记）。加固方向：**按用途
隔离各自的稳定直出 session**，并统一配置到网关层，加直出验证。

## 改了什么

- **`eval/gateway.py`**（统一配置源）：
  - `PURPOSES=(parse,eval,verify)` 与 `DEFAULT_PURPOSE_SESSIONS`（parse-01 / eval-01 / verify-01）。
  - `resolve_session_for(purpose, model)`：`GRAPH2NOTE_SESSION_<PURPOSE>` > 历史
    `GRAPH2NOTE_OPENCODE_SESSION`/`OPENCODE_SESSION` > 用途默认；未知用途 ValueError。
  - `resolve_sessions(model)` eval 主会话走用途解析；`validate_session_direct()`（进程级缓存、
    64-token 探针、reasoning-runaway 判据）、`session_validation_enabled()`/`maybe_validate_direct()`
    （`GRAPH2NOTE_VALIDATE_SESSIONS=1` 时首解析探测）。
- **`graph2note/vlm.py`**：`resolve_session(model)`→parse 用途（默认 `graph2note-parse-01`）；
  `STABLE_SESSION`/`VALIDATED_SESSION` 同步；env 校验开关接通。
- **`graph2note/router.py`**：`RouteARouter(session=None)` 默认走 parse 解析（原硬编码 parse-route-a）。
- **`graph2note/verify/engine.py`**：verify 基座 `resolve_session_for("verify", model)` →
  `graph2note-verify-01-<model>`（每模型后缀保留，旧 `graph2note-crossval` 经 env 还原）。
- **`scripts/validate_sessions.py`**：三用途各验一次（预算 ≤3）。
- **`docs/llm/opencode-go.md`** §2.1：会话隔离使用规范（争用现象、隔离表、env、验证开关）。

## 验证

- live（3 次调用，每用途一次）：三 session 全部 status=ok、reasoning_tokens ≤63（≪800）、直出可用。
- 离线：`pytest tests/` **236 passed, 2 skipped**（基线 217 → +19；新增 gateway 会话解析/覆盖/验证判据 +
  vlm/router/verify 委托测试）。

## 给接手/main 的注意事项

- 历史 `graph2note-spike-01` 只作未知用途兜底只读常量保留；要复现旧行为用
  `GRAPH2NOTE_SESSION_<PURPOSE>=graph2note-spike-01` 或 `OPENCODE_SESSION`。
- 若引入强推理路由/重验证：调整 `PROBE_MAX_TOKENS` 或阈值 `RUNWAY_REASONING_TOKENS` 复核。
- 新默认 id 首次无 prompt 缓存，预热后既有；正确性无影响，仅首一段路由略慢。