# 视觉模型评估/解析链路单次调用延迟诊断报告

> 供 issue 11（解析提速，P95 ≤ 60s）与 PRD「性能预算（P1 增补）」消费。
> 执行：AO 诊断 worker · 分支 dev/diag-eval-latency · 2026-09-08 08:47–09:10 UTC
> 只诊断/报告，未改动 eval/、spike3/ 等共享代码；新增文件均在 `reports/data/latency_diag/` 与本文档。

## 0. 一句话结论

单次调用慢不是「网络慢」或「输出长」，而是**模型在 10k `max_tokens` 预算内持续输出 `reasoning_content`（思考）**：DeepSeek 固有推理 3.4–4.9k tokens → 每条成功调用 50–65s；glm 在部分会话路由下会**思考狂暴（runaway）直至吃满 10000 token 预算** → 300–407s 且正文为空，随后产品侧还会再走一次回退重试（隐性双倍调用），端到端可达 300s+。其余因素（图片尺寸、网关抖动、串行）为次要项。

---

## 1. 方法

纪律化诊断五步：复现 → 最小化 → 假设 → 插桩 → 结论。真实 LLM 调用配额 8 次（5h / $12），本文实验占用 **8 次**（见 §2），pytest 全绿（52 passed, 2 skipped，离线，不触网）。

- 插桩客户端：`reports/data/latency_diag/scripts/call.py`（**只读 import** `eval.gateway` 的 prompt 常量保证与生产 byte 级一致；streaming 逐 chunk 计时区分 prefill / reasoning / content 三阶段；非流式对照复现生产路径）。
- 每次调用写 `reports/data/latency_diag/calls/<tag>.json`（含耗时/usage/reasoning tokens/正文长度）。汇总表见 `calls/_summary_table.json`。
- 图像变体（离线 PIL 生成，仅改变尺寸/压缩）：`reports/data/latency_diag/images/`（w1024_q85=128KB、w768_q80=68KB，原图 898KB）。

---

## 2. 现场实验证据表（8 次调用，UTC 2026-09-08 08:47–09:10）

| # | tag | 模型 | session | 图宽 | stream | max_tk | total s | reasoning_tk | 正文 chars | finish | prompt_tk | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | c1 | glm | `diag-glm`（新） | 1920 | Y | 10000 | **300.3** | 9886 / 10000 | **0** | length | 2875 | runaway，全吃预算空正文 |
| 2 | c2 | glm | `diag-glm`（新） | 1024 | Y | 10000 | 152.2* | —（~4600 估） | **0** | 中止 | — | runaway，→150s 客户端中止 |
| 3 | c3 | glm | `diag-glm-ns`（新） | 1920 | N | 10000 | **407.4** | 9530 / 10000 | **0** | length | 2875 | **生产等价非流式** runaway |
| 4 | c4 | glm | `spike-01`（稳定） | 1920 | Y | 10000 | **18.4** | **0** | 787 | stop | 2875 | 直出、无思考 |
| 5 | d1 | deepseek | `spike-01` | 1920 | N | 10000 | **52.1** | 3389 / 3625 | 689 | stop | 623 | 固有推理，可出正文 |
| 6 | d2 | deepseek | `spike-01` | 1920 | N | 2000 | **26.3** | 2000 / 2000 | **0** | length | 638 | 「直出+cap」对 ds 无效 |
| 7 | g5 | glm | `spike-01` | **1024** | N | 10000 | **7.6** | 0 | 853 | stop | **961** | 降采样直出最快 |
| 8 | g6 | glm | `spike-01` | 768 | N | 10000 | **40.2** | 0 | 593 | — | 632 | 无思考却慢 → 抖动 |

\* c2 为客户端 150s 中止的 partial（服务端彼时仍在生成，tokens 照计）。

对比既有冒烟（05:39–05:42 UTC）非流式：glm S01 01图 40.7s(246 tk)、02图 19.25s(167 tk, **retried=True**，首次空正文后走回退)；deepseek S01 01图 64.46s(4909)、02图 54.07s(5547)。spike3（session `graph2note-spike3`）2 张真实大图：deepseek 均空正文、glm R02 空正文（记录在案）。

---

## 3. 假设逐项检验

### H1 图片尺寸 → 视觉输入 token 与延迟
- 实验（同 session S01、同 prompt、非流式直出）：glm prompt_tokens 1920=**2875** / 1024=**961** / 768=**632**；延迟 18.4 / **7.6** / 40.2s；上传体积 898KB / 128KB / 68KB。
- 数据：输入 token 与像素强相关（尺寸减半 → token 约 1/3）；典型延迟 1920→1024 降约 2.4×；但 **768 反升到 40.2s**，被抖动覆盖，无单调收益。deepseek 原图已压缩至 623 tokens（与文本同量级），尺寸非其杠杆。
- 结论：**成立但不充分**。降采样是真实杠杆（省输入 token、降典型延迟、省上传），但对 P95 抖动与 runaway 无效；768 档出现正文变短（853→593 chars）疑有质量损失。

### H2 reasoning_content 生成耗时
- 实验：比较各调用 reasoning_tokens 与总耗时——c1 9886→300s、c3 9530→407s、d1 3389→52s、既有 ds 4909/5547→64/54s；直出路径（c4/g5/g6）reasoning=**0** → 7.6–40s。
- 数据：**reasoning tokens 是延迟的直接载体**；生成速率约 25–35 tok/s（glm runaway）到 ~70 tok/s（ds），即每千 reasoning token ≈ 30–40s。小 `max_tokens` 对 deepseek 无效：d2 吃满 2000 仍空正文（「直接给结果，不要思考」也拦不住）；对 glm 直出路由则根本无思考。
- 结论：**成立，为主因**。压缩/消除 reasoning 收益最大；单纯设小 `max_tokens` 会截断在思考处→空正文，是陷阱而非杠杆。

### H3 x-opencode-session 复用 vs 每次新 session
- 实验：同图（1920 01-arch）+同 prompt +同模型 glm，仅换 session：`spike-01`（评估在用）→ 18.4s 直出；`diag-glm`/`diag-glm-ns`（新建）→ 300–407s runaway 空正文（已 3 次复现跨 2 个新 session）。
- 数据：**~20× 差异**，reasoning 0 vs ~9.5k。所有调用 `usage.prompt_tokens_details.cached_tokens=0`，即**非 prompt 缓存**，而是 **session 决定路由到不同上游变体**（直出 vs 推理）。
- 结论：**成立（强关联，量级极大）**。会话路由不当时 glm 会以推理变体运行；复用已验证的稳定 session 是规避 runaway 的最大抓手。

### H4 网关排队/模型档位/抖动
- 实验：同配置重复/近距对比——glm S01 直出：1920 stream 18.4s vs 历史 40.7s；1024 7.6s vs 768 **40.2s**（均零思考、completion ≤280）；prefill 到首 delta 7–13s。
- 数据：零思考的直出调用仍会出现 ~40s 的离群（同配置跨 5 倍），prefill 抖动 ±7s。当前为 deepseek 高峰窗口（UTC 06–10）并叠加一般负载。
- 结论：**成立**。服务端抖动是「单次 P95 ≤ 60s 预算内」仍被抓的关键来源之一；无法用客户端入参消除，需超时/降级兜底。

### H5 串行执行
- 实现审读：`eval/harness.py` `EvalRun.run()` 逐 sample `for` 循环串行，每页一次 `transcribe_image`，无并发；`gateway.transcribe_image` 内无并发。
- 结论：**吞吐瓶颈，非单次延迟根因**。多页文档 e2e=Σ 单页（30–50 页≈25–50min）；对单页 P95 无影响。

### H6 失败重试/空内容隐性双倍调用
- 实验/证据：c1/c3 演示 runaway→空正文（http 200、`content` 空、`finish_reason:length`）；产品 FALLBACK 会对空正文再发 `max_tokens∈{2000,1200}` 的直出重试（glm-02 评估 meta `retried=True` 在案；deepseek 回退仍空，见 d2）。c2 演示客户端超时中止后服务端仍继续生成（双计费）。
- 结论：**成立**。空内容/超时使单页 e2e 最坏 **300s+（runaway 首调）+ retry**，远超 60s 预算；是「偶发特别慢」与成本翻倍的来源。

---

## 4. 根因结论（按对单次调用延迟的贡献度排序）

1. **`reasoning_content` 长思考/思考狂暴（runaway）** —— 慢的直接载体。DeepSeek 固有推理 3.4–4.9k tokens → 50–65s/条；glm 在推理路由下吃满 10k 预算 → 300–407s 且空正文。占总延迟的绝大部分。
2. **会话路由决定 upstream 变体（直出 vs 推理）** —— 诱发 glm runaway 的开关。同图同 prompt 仅换 session 使 glm 从 18s 变 300s（≈20×），量级最大；同时造成空正文。
3. **服务端抖动/排队** —— 直出模式下 7.6–40s 波动（同配置 5×），是「预算内 19–65s」波段与 P95 超线的主要来源；与高峰窗口相关。
4. **失败重试/空内容的隐性双倍调用（含超时后双计费）** —— 把最坏 e2e 推到 300s+，且放大成本。
5. （次要）**输入图 token 开销**（glm 3×）、**串行吞吐** —— 前者省成本/典型延迟，后者只影响多页端到端。

> 说明：保留地看待"session→上游变体"的机制结论——本项目自数据虽强（Q1 回归一致、3 个 new session 全 runaway、spike-01 两次直出），但为供应商内部路由实现，未做跨时段对照；建议 issue 11 以受控探针复核（见 R1 风险）。

---

## 5. 给 issue 11 的优化建议排序（预期收益 / 风险）

| 优先级 | 建议 | 预期收益 | 风险 / 待验证 |
|---|---|---|---|
| **P0** | **R1 固化并校验稳定 session**：每个模型一个长生命、已验证为「直出模式」的固定 `x-opencode-session`；解析响应记录 `reasoning_tokens`，超阈值告警/切换 | 消除 glm runaway 尾（300–407s）与连锁空正文重试；单页典型 8–40s | 路由语义在供应商侧，可能随负载/时段漂移 → 需周期性侦测（低成本，读响应 reasoning_tokens 即可）+ 监控 |
| **P0** | **R2 首调即用「直出约束 prompt + 中等 max_tokens」（约 3000–4000）**，把当前 FALLBACK「10k 空转后才回退」改为「首次就直出」 | 单页最坏 e2e 从 300s+ 压回 ~单次直出；ds 需配 R1 | glm 直出质量回测（eval-02 曾以 retry 直出成功 167tk/19.25s，正样本在手）；**对 deepseek 无效**（d2） |
| **P1** | **R3 图片降采样 ~1024px（q85）上限再送 glm** | 输入 token 3×↓（2875→961）、典型延迟 18.4→7.6s、上传 7×↓ | **768 px 有正文变短迹象（质量待评估集 EditRate 回测）**；从 1024 起步勿激进；对 deepseek 无收益（输入已压到 623） |
| **P1** | **R4 客户端硬超时 + 空内容/超时后切换策略而非同参重试**（如超时→换 session / 换模型 / 降采样） | 兜住 H4/H6 最坏路径 | 超时后服务端仍生成计费的账单风险需提示；需防重复触发高成本 run |
| **P2** | **R5 双模型交叉验证成本再核算**（issue 10）：deepseek 每条固定 50–65s，与 glm 串行交叉验证单页 ~70–105s | 明确预算是否需修订 | 若必须满足 60s，交叉验证需并行或 deepseek 仅用于小图/分歧复查 |
| **P2** | **R6 多页/双模型并发化**（线程池小并发 2–4） | 缩短多页 e2e（吞吐，P2 场景） | 网关并发配额未验证；单页 P95 不变 |

第一落地点：**R1 + R2**（同一根因的两面：遏制 runaway/空转），R3 作为安全省 token 的次优，R4 作兜底。所有质量类改动以评估集 EditRate 回测为门槛（与 issue 01 共享）。

---

## 6. 限制与开放问题

- 样本规模小：仅 `01-requirements-arch.jpg`（一幅复杂流程图）与 2 模型、若干 session；`02-digitize-pipeline` 未重新测量（复用既有冒烟 19.25/54.07s）。
- 未实测的候选：glm + **直出 prompt + 新 session** 是否仍 runaway（若否，则无需依赖 session 即可规避——留给 issue 11 第一笔实验，本报告预算已用尽）；API 是否存在「关闭思考/低推理 effort」参数（供应商待核实，若能则 ds 50–65s → ~10s 是最大单点收益）。
- 高峰窗口（06:00–10:00 UTC）与各时段的延迟带宽未做跨时段采样。
- `cached_tokens` 恒为 0：本 gateway 对含图片的 prompt 未见命中 prompt 缓存（图片为可变前缀），「同会话同图缓存」的既有假设在此数据集上未得到 token 级证据。

## 7. 复现方法与数据索引

- 插桩/复现脚本：`reports/data/latency_diag/scripts/call.py`
- 逐调用记录：`reports/data/latency_diag/calls/*.json`（8 条）；汇总：`calls/_summary_table.json`
- 图像变体：`reports/data/latency_diag/images/`
- 密钥仅从环境变量读取，脚本/证据不落任何 key。
- 分支 `dev/diag-eval-latency`，本报告未改共享代码。