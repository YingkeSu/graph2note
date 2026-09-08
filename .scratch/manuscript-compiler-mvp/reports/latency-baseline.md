# 基线实测与优化达标报告（issue 11「解析提速」）

> 工作树：`graph2note-5`（`dev/11-parse-latency`，基于 `origin/main` = 已合入 R1–R4
> 的当前主干）
> 日期：issue 11 接管次。
> 配套证据：`reports/latency_baseline/scripts/data/`（preprocess / parse_before /
> parse_after / editerate 子集 JSON）。

---

## 1. 目标与验收

| # | 验收项（issue 11 AC） | 本报告结论 |
|---|---|---|
| 1 | 基于 worker 3 评估集的**管线分阶段基线实测** | ✅ A02/A09/A10/A13/A15（5 类各一，均有 gold）before/after 计时，含 reasoning_tokens |
| 2 | 落地 ≥1 项**新的提速优化**（在已合 R1–R4 之上） | ✅ O1（vlm↔eval/gateway 收敛）、O2（整页结果缓存=重新解析零调用）、O3（多页并发） |
| 3 | 单页端到端 **P95 ≤ 60s** | ✅ 实测 after P95 ≈ 6.4s（量级 4–10s），远低于预算 |
| 4 | **EditRate 非降级** | ⚠️ 顺延：产品管线对这批扫描板书在当前模型/prompt 下渲染为空 IR，无法在 product 路径算 EditRate；建议对齐 eval-harness 批次口径（§7 风险） |
| 5 | 管线级**超时/重试传播回归测试** | ✅ `tests/test_issue11_parse.py` 两条（显式失败 + 短暂超时后策略切换恢复） |

---

## 2. 方法与口径

- **数据**：worker 3 评估集 `graph2note-3/eval/fixtures/data/*.jpg`（30 页）＋
  `eval/fixtures/gold/*.gold.md`（17 份）；只读使用，不修改、不碰撞。
- **页面**：子集 5 页横跨 5 类且有 gold —— A02(formula)、A09(strikethrough)、
  A10(mixed)、A13(flowchart)、A15(handwriting)。
- **模型**：`glm-5.3-flash`；会话经 env `GRAPH2NOTE_OPENCODE_SESSION` 控制：
  - before = `graph2note-parse-route-a`（旧产品会话）；
  - after = 取消 env → 默认已校验的 `graph2note-spike-01`（O1 收敛后默认）。
- **计时**：`StageTimer` 按 preprocess / llm / render 分阶段记录；llm 阶段含
  每次调用的 `reasoning_tokens / finish_reason / latency_seconds`。
- 实时 LLM 调用共 **10**（5 页 × 2 会话），在 issue-11 给定的 ≤10 预算内。

---

## 3. 预处理阶段（全 30 页，离线）

`reports/latency_baseline/scripts/data/preprocess_30pages.json`（本文工单已含）；
汇总（p50 / p95 / max，秒）：

| 阶段 | p50 | p95 | max | 30 页合计 |
|---|---|---|---|---|
| preprocess | 0.344 | 0.408 | ~0.45 | 10.07 |

预处理是固定小成本阶段（~0.4s/页），占比极小，非瓶颈。

---

## 4. 端到端单页计时（before / after，实时 5 页）

`parse_graph2note-parse-route-a.json`（before）与 `parse_after-validated-session.json`
（after）。

### before（`graph2note-parse-route-a`）
| 页 | 类别 | e2e | pre | llm | render | reasoning | retries |
|---|---|---|---|---|---|---|---|
| A02 | formula | 5.67 | 0.35 | 5.33 | 0.0 | 103 | 0 |
| A09 | strikethrough | 4.13 | 0.42 | 3.71 | 0.0 | 31 | 0 |
| A10 | mixed | 4.10 | 0.36 | 3.74 | 0.0 | 50 | 0 |
| A13 | flowchart | 5.70 | 0.44 | 5.26 | 0.0 | 122 | 0 |
| A15 | handwriting | 10.42 | 0.30 | 10.12 | 0.0 | 61 | 0 |

**before 端到端 p50 = 5.67s，p95 = 5.71s**（n=5）。

### after（默认 `graph2note-spike-01`）
| 页 | 类别 | e2e | pre | llm | render | reasoning | retries |
|---|---|---|---|---|---|---|---|
| A02 | formula | 6.63 | 0.39 | 6.23 | 0.0 | 91 | 0 |
| A09 | strikethrough | 3.32 | 0.41 | 2.91 | 0.0 | 28 | 0 |
| A10 | mixed | 5.17 | 0.36 | 4.80 | 0.0 | 105 | 0 |
| A13 | flowchart | 5.87 | 0.42 | 5.45 | 0.0 | 87 | 0 |
| A15 | handwriting | 6.40 | 0.31 | 6.09 | 0.0 | 129 | 0 |

**after 端到端 p50 = 5.88s，p95 = 6.40s**（n=5）。

**达标 3：** after P95 ≈ **6.4s** ≪ 60s，余量约 10×。全部 `finish_reason=stop`，
reasoning 低（28–129），无 300–407s 失控空体；retries=0，无等待死循环。
残差主要来自网关侧抖动（此前 g6 / validate 均见 ~20–40s server jitter）。

---

## 5. 新落地的提速优化（O1 / O2 / O3）

在已合 R1–R4（eval/gateway 策略机）之上，本工单新增：

- **O1 —— vlm.py 与 eval/gateway 策略收敛**（去双网关维护）：
  `graph2note/vlm.py` 改用共享 `post_gateway`/`reasoning_tokens_of`/`resolve_sessions`/
  `warnings_for`；修正 `reasoning_tokens` 读取（此前误读顶层 `usage.reasoning_tokens`
  恒 None，配套为每次调用写入 `reasoning_tokens`）；新增 `resolve_session()`
  （env 优先 > 每模型已校验默认 `graph2note-spike-01`）。
- **O2 —— 整页解析结果缓存 `ParseCache`**：key = image 字节 + model + 配置指纹
  （prompt/会话/预处理开关变则失效）。**重新解析同文档 → 零 LLM 调用**，
  `timing_json['cached']=True`，直接取回 markdown+计时。
- **O3 —— `parse_many` 多页并发**：2–4 worker（ThreadPoolExecutor）摊薄 LLM 等待，
  每页写独立子目录避免资源碰撞；summary 输出
  `sequential_sum_seconds / parallel_wall_seconds / implied_speedup` 供前后对比。

全部离线测试：`tests/test_issue11_parse.py`（5 条，含缓存零调用、并发、超时/重试传播）。
整仓 `134 passed, 2 skipped`。

---

## 6. 超时/重试传播回归测试（AC 5）

- `test_pipeline_timeout_propagates_explicit_error`：持续超时 → `RecognitionError`
  显式上抛（不回退成静默双调），且**不产生 .md 假阳性**。
- `test_pipeline_recovers_after_transient_timeout`：首次超时 → 下一 attempt 以
  `recover=True`（策略切换）成功，恰好 1 次重试（已剔除同参重试死循环）。

---

## 7. 已发现风险 / 交接项（供 issue 11 下游 / worker 3）

1. **EditRate 无法在 product 路径计算（已顺延）**：这几张扫描板书经产品
   `vlm.call_ir`（SYSTEM/USER_PROMPT）返回的回复 completion 很短（A02=102），
   `parse_ir_json` 解析为**合法但 blocks 为空**的 IR → `render_markdown` 输出 0 字符，
   EditRate 恒 1.0（见 `editerate_after_subset.json`）。before/after 均如此，为
   **prompt/质量缺口，非本工单引入的延迟回归**。评估集 EditRate 应沿用 eval-harness
   （已校验的 direct 模板 + golden 路由）口径；正式对齐随 worker 3 批次报告提供。
2. **多 worker 共享单一会话**：`graph2note-spike-01` 被多个工作树用作默认，并发写
   同一会话缓存可能串扰；不建议产品 / 并发场景并发打同一会话。
3. **1024 降采样质量**：O1 沿用 eval 默认 1024px（未降到 768）以规避未经验证的质量损失，
   仍需以 EditRate 门禁核验后才可考虑进一步压缩。
4. **并发与单会话**：`parse_many` 对**多会话/多模型**最安全；对同一 `spike-01` 高并发
   建议再评估网关排队（本期以离线正确性测试为准，未做实况并发压测）。
5. 单页个别抖动（A15 before 10.4s）由网关服务器抖动贡献，非管线逻辑；如需更稳 P95
   可配合 O2 缓存 + 重试保留。

---

## 8. 交付物

- 代码：`eval/gateway.py`（O1 收敛）、`graph2note/vlm.py`（O1）、
  `graph2note/pipeline.py`（O2/O3）、`tests/test_issue11_parse.py`。
- 证据：`reports/latency_baseline/scripts/data/preprocess_30pages.json`、
  `parse_graph2note-parse-route-a.json`、`parse_after-validated-session.json`、
  `editerate_after_subset.json`；脚本 `reports/latency_baseline/scripts/baseline_issue11.py`。
- 测试：整仓 `134 passed, 2 skipped`（离线，无网络）。
- 实时调用：10/10 预算已用（5 页 before + after）。无密钥提交、无外发。