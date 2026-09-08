# Handoff — issue 11「解析提速：基线实测与优化达标」

> 来源：worker 5（graph2note-5，`dev/11-parse-latency`）
> 交接给：issue 11 接手者 / worker 3（编辑率口径）/ dispatcher
> 上游：接 handoff 03（parse-pipeline-cli）→ 09（pdf 拆分）→ 本 issue。

## 做了什么（可验证交付）

1. **分阶段基线实测**（`reports/latency-baseline.md`，证据 `reports/latency_baseline/scripts/data/`）：
   worker 3 评估集 30 页预处理离线计时 + 5 页（A02/A09/A10/A13/A15，5 类各一且有 gold）
   before/after 全管线计时，含每 attempt `reasoning_tokens/finish_reason/latency`。
   - after（默认 `graph2note-spike-01`）e2e **p50=5.88s / p95=6.40s**，量级 4–10s；
     全部 `finish_reason=stop`，reasoning 28–129，retries=0，**无 300–407s 失控空体**。
   - 达标 3（P95 ≤ 60s）余量约 10×。
2. **三重新优化**（在已合 R1–R4 之上）：
   - **O1** `graph2note/vlm.py` ↔ `eval/gateway.py` 收敛：共享 `post_gateway`/
     `reasoning_tokens_of`/`resolve_sessions`/`warnings_for`；修正 reasoning 读取
     （旧误读 `usage.reasoning_tokens` 恒 None）；新增 `resolve_session()`
     （env > 每模型已校验默认）。去双网关维护。
   - **O2** `graph2note/pipeline.py` `ParseCache` + `parse_document(result_cache=)`：
     key=image字节+model+配置指纹；**重新解析同文档 → 零 LLM 调用**。
   - **O3** `graph2note/pipeline.py` `parse_many`：2–4 worker 多页并发摊薄 LLM 等待，
     每页独立子目录，输出 sequential/parallel speedup 口径。
3. **超时/重试传播回归测试**：`tests/test_issue11_parse.py`（显式失败 + 短暂超时后
   recover 恢复各 1 条）＋ 缓存零调用、并发、模型分区键。
4. 整仓 **134 passed, 2 skipped**（离线，无网络）。

## 关键决策 / 口径

- 实时预算 ≤10 已用尽（5 页 × before/after）。复测优先用 O2 缓存或 worker 3 已跑批次。
- 会话：product 默认收敛为 `graph2note-spike-01`；before=`graph2note-parse-route-a`。
- 共享会话不用于并发压测（多 worker 共享同会话有串扰风险）。

## 打开的风险 / 待决

1. **EditRate（AC 4）顺延**：产品 `vlm.call_ir` 对这批扫描板书返回 completion 很短
   （A02=102 token），`parse_ir_json` 解析为**合法但 blocks 为空**的 IR →
   `render_markdown` 输出 0 字符，EditRate 恒 1.0（`editerate_after_subset.json`）。
   before/after 一致，为 **prompt/质量缺口，非本工单引入的延迟回归**。
   · 建议：评估集 EditRate 用 **eval-harness**（已校验 direct 模板 + golden 路由）口径，
   与 worker 3 批量对齐；如需 product 路径改善，另立 prompt 质量 issue。
2. 并发对同一 `spike-01` 的网关排队未做实况压测（仅离线正确性）。
3. 1024 降采样质量仍需 EditRate 门禁核验后再考虑进一步压缩。

## suggested skills（接手者）

- 复测延迟：跑 `reports/latency_baseline/scripts/baseline_issue11.py`（需 `.env` 密钥 +
  worker 3 数据路径 + `GRAPH2NOTE_OPENCODE_SESSION`）。
- EditRate 对齐：看 `eval/editerate.py`、worker 3 `eval/reports/`。
- 质量缺口：readonly 检查 `graph2note/vlm.py` SYSTEM/USER_PROMPT 与 `router._parse_to_ir`。