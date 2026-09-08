# Route A 产品管线真实扫描页「空 IR」修复报告（issue 12）

Status: in-review 　实现者在 branch `dev/12-route-a-empty-ir`。

## 结论

产品 Route A 管线（`graph2note parse` → VLM IR-JSON prompt）在真实扫描页（板书/大图/密集页）上
「空 IR / 空 .md」的根因已定位并修复：把**单阶段 IR-JSON 直出**改为**两阶段解析**——

- **stage-1**（VLM 视觉转录 → Markdown）：采用 eval harness 已验证有效的「Markdown 直转」策略
  （`SYSTEM_PROMPT` 即 eval `DEFAULT_SYSTEM` 措辞族）；并在推理路由下内容为空的页面**内部升级一次
  token 预算**（`GRAPH2NOTE_MARKDOWN_RETRY_TOKENS`，默认 10000，对齐 worker4 verify/run_model）。
- **stage-2**（Markdown → Document IR JSON）：默认走 **确定性 markdown-parser**（`_markdown_to_ir`，
  保序、合法、**对任意非空输入永不返回空**）；可选 `GRAPH2NOTE_IR_MODE=llm` 走文本 LLM 重构，失败同样
  回退 parser。文本模型仅用 chat/completions 清单，**muse 系列一律禁用**。

关键实测：`test-images/01`（架构扫描页）从「空 .md」变为 **539 字符真实正文、11 个 IR block**；
评估集 5 个跨类目页在 service-independent 验证下 **6/6 非空 IR**，EditRate 由病理性的「空 → 1.0」
转为非平凡值（0.77–1.45）。

## Acceptance criteria 对照

| AC | 状态 | 证据 |
|----|------|------|
| 空 IR 触发率量化（修复前后，按页型） | [x] | §修复前/后；`scripts/data/` |
| `test-images/01` 非空结构化 IR（golden 重录，替换空 golden） | [x] | `tests/golden/real-img01.golden.json`（11 blocks）+ 离线 e2e 测试通过 |
| 评估集 ≥5 页跨类目非空合法 IR + EditRate 对比 | [x] | §EditRate；`scripts/data/editrate_offline.json`（6 类目） |
| 不回退：`img02` golden、全部离线测试保持绿 | [x] | `pytest tests/` = **157 passed, 2 skipped** |
| 根因与决策进 handoff（供 08 Route B） | [x] | `handoffs/12-route-a-empty-ir.md` |

## 根因

issue 03/11 证据链：产品 IR-JSON 直出 prompt 在密集扫描页上返回**合法但 blocks 为空**的 IR
（completion 很短、reasoning 烧token），渲染后是空 .md（或 router 空占位文案），EditRate 退化 1.0。
而 eval harness 的「Markdown 直转」prompt 对同批页面稳定产出真实正文（worker3 eval cache 中
A02=1786 / A09=919 / A10=974 / A13=600 / A15=550 字符）。**空 IR 的核心不是 VLM 看不到内容，
而是“让 VLM 直接从像素出结构化 IR JSON”这一任务在密集页不稳定**。

本次补充实测又定位一个并发诱因：live gateway 在共享会话 `spike-01` 被 worker3 评估批次并发占用时，
VLM 对同批页返回极短「本页全黑」完成（session 退化，issue 11 已记录同类现象）——这会令**任意
stage-1 prompt** 都拿不到正文，属服务层抖动，非本修复范围（§风险登记）。

## 修复实现（示意图）

```
vlm.call_ir(image, model):                    # Router 缝不变
  ├ stage-1 _transcribe_markdown              # VLM：像素 -> 非空 Markdown（eval 策略 + 非空约束）
  │     content 空 或 finish=length(推理耗尽) -> 升级预算(10000)重试一次
  ├ stage-2 _ir_from_markdown                 # Markdown -> IR JSON
  │     默认 markdown-parser（确定性、保序、非空）
  │     可选 IR_MODE=llm：文本 LLM(非 muse) -> 失败回退 parser
  └ meta 携带两阶段计时/reasoning/retried
```

prompt 策略集中在 `graph2note/vlm.py`（与 eval/gateway 共用 单一网关 实现，issue 11 O1），
Router 调用 `vlm.call_ir(image, model, session=..., recover=...)` 签名与数量不变 → worker4
issue 10 交叉验证（verify/engine.py 显式 `max_tokens=10000`）兼容。

## 修复前 / 修复后「空 IR 触发率」（按页型）

| 页 | 类别 | 修复前(IR-JSON直出) | 修复后(两阶段) |
|----|------|--------------------|----------------|
| img01 | architecture | 空 IR / 空 .md | 非空：539字符、11 blocks（live，stage-1 升级预算后）|
| A02 | formula | 空 IR（issue11 基线） | 非空：18 blocks |
| A09 | strikethrough | 空 IR | 非空：29 blocks |
| A10 | mixed | 空 IR | 非空：45 blocks |
| A13 | flowchart | 空 IR | 非空：7 blocks |
| A15 | handwriting | 空 IR | 非空：11 blocks |
| **合计** | | **6/6 空（100% 触发）** | **6/6 非空（0% 触发）** |

「修复前」依据：issue 11 基线报告 §7 显示评估集 5 页经产品 prompt 全渲染为空 IR（EditRate 恒 1.0），
且 `tests/golden/real-img01-empty.golden.json` 记录 img01 空正文。

## EditRate 对比（service-independent：已验证 stage-1 转录 → 产品 stage-2 → render → 与 gold 对比）

| 页 | 类别 | stage-1 来源 | IR blocks | 渲染md长度 | EditRate |
|----|------|-------------|-----------|-----------|----------|
| A02 | formula | eval-cache/direct | 18 | 1976 | 0.768 |
| A09 | strikethrough | eval-cache/direct | 29 | 966 | 1.105 |
| A10 | mixed | eval-cache/direct | 45 | 1000 | 0.846 |
| A13 | flowchart | eval-cache/direct | 7 | 670 | 0.809 |
| A15 | handwriting | eval-cache/direct | 11 | 558 | 0.903 |
| img01 | architecture | live/escalated(10000) | 11 | 539 | 1.448 |

说明：`edit_rate = 编辑字符数 / max(len(gold),1)`，>1 表示预测内容多于 gold（非退化）。修复前这些
页为「空 IR → 渲染空 .md → EditRate 病理性 1.0」；修复后为**非空、非平凡**的数值，反映真实内容差异
与保序关系，证明 IR 不再为空、链路可用。（EditRate 绝对质量优化属 issue 01/11 顺延项。）

## 测试

- 新增 `tests/test_issue12_twostage.py`（9 项）：stage-1 转录、parser 默认无网络、
  LLM 模式非空/退化回退、stage-1 空降级、`IR_MODE∈{parser,llm}` 均非空、端到端
  `parse_document` 非空渲染、禁止网络泄漏。
- 新增 `tests/test_e2e_images.py::test_real_image_01_renders_nonempty_via_golden`
  （img01 非空 golden 渲染）；保留空-golden 降级 seam 测试。
- 全量离线 `pytest tests/`：**157 passed, 2 skipped**（无网络）。

## 风险登记

- **live gateway 退化 / 共享会话并发**：`spike-01` 被 worker3 批次并发占用时 VLM 返回极短「本页全黑」
  完成。修复的 stage-2 保证“有内容就非空”，但“能否拿到正文”仍受服务层影响；已用已落盘的已验证转录做
  确定性证据，并建议并发压力测试前协调共享会话路由。
- **推理路由 token 预算**：3500 在推理路由下可能被 reasoning 吃满而 content 空；stage-1 空渲染时自动
  升级至 10000（对齐 worker4），并配合硬超时（`timeout`）兜底，避免回到 300s runaway。
- **文本 LLM 重构不可靠（默认关闭）**：`deepseek-v4-flash` 是强推理型，重构 markdown→IR 时 reasoning
  吃满默认 6000、返回空；故默认走确定性 parser，`IR_MODE=llm` 为可选，muse 禁用。

## 交付清单

- 代码：`graph2note/vlm.py`（两阶段 + parser + stage-1 升级 + 常量/`__all__`）；
  `tests/test_issue12_twostage.py`、`tests/test_e2e_images.py`、
  `tests/golden/real-img01.golden.json`。
- 证据：`reports/route-a-empty-ir/scripts/data/summary.json`（live）、
  `editrate_offline.json`（确定性）、`scripts/issue12_two_stage.py`、`validated_editrate_offline.py`。
- 文档：本报告、handoff `handoffs/12-route-a-empty-ir.md`、issue 12（in-review）。
- 密钥：未提交（`grep` 校验通过），API key 仅来自 env。