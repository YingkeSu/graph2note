# D5a — 抽取 prompt 调优（note / dashed / 防弱关联丢失）handoff

Status: **ready-for-review**
分支：`dev/D5a-prompt-tune`（基线 `883f8cb` = D4 合并后 main；未合并、未 push）
日期：2026-09-15
领地：`graph2note/diagram.py` 的 `SYSTEM_PROMPT` 字符串 + `tests/test_diagram_groups_ir.py` 单测。
未改 renderer / `_layout` / 渲染层 / 配置常量。

提交（`git log 883f8cb..HEAD`）：

| SHA | 内容 |
|---|---|
| `0a88db0` | prompt note/dashed/防丢失规则 + 单测 |
| HEAD | 见分支尾（handoff docs commit） |

依据：`/tmp/spw-T-vision-recheck-live.md` §7-1/2/4 与 §9 裁决（§7-3 设备归组**未执行**）。

---

## §0 验收线结果

| 验收线 | 结果 | 证据 |
|---|---|---|
| 01 `notes ≥ 2`，且 VNC 警告 + critical path 进 note | ✅ **4 条 note**，含 `坑：Tiger VNC 不支持`、`亮点：Critical path 优化 ☆` | §3 |
| ≥1 图产出 dashed 边（02「参考」→dashed 预期） | ✅ **01=1 条、02inc=5 条**（含 label=参考/备选/同步）；02 本样本 0 条（见 §5） | §3 |
| 02「参考」弱关联保留 | ✅ 调研节点 `n5`→解析层 `n7`（及 `n6→n7`）的关联被保留，未再整条丢弃（以边表达） | §3 |
| `validate_diagram_json` 全 ok | ✅ 3/3 `revalidate=ok` | §3 |
| 不编造层次（组结构与现有 live 一致） | ✅ 组均为手稿真实区域；计数/kind 随采样波动（VLM 单次采样固有），prompt 未改分组规则 | §4/§5 |

全量 `pytest -p no:warnings` → **1040 passed**（基线 1037 + 新增 3）。

---

## §1 prompt 改动（`SYSTEM_PROMPT`）

仅改提示词字符串，`validate_diagram_json` / schema / 渲染层零改动。

1. **note 通道（规则 3，新增）**：评价性短句（警告/坑/不支持/注意/风险/限制/亮点/优化/优点/缺点/
   建议/备注）**不建节点**，写成语义最相关节点的 `note`；给出两个 01 锚点示例：
   「坑：Tiger VNC 不支持」→ 相关节点 note；「亮点：Critical Path 优化 ☆」→ 相关节点 note。
2. **dashed 通道（规则 4，强化）**：松散/说明性关联，或文字写明「参考/可选/备选/弱引用/跨组引用」，
   该边用 `style:"dashed"` 并保留原文 label；给出 `参考` 的 JSON 示例。
3. **防弱关联丢失（规则 5，新增）**：「参考/虚线/跨组弱引用」类关系不得整条丢弃，必须用 dashed 边
   或相关节点 note 表达，不得因为「不是主流程」而省略。
4. 规则 1（groups/layer/lane/cluster）**原样未动**；§7-3 设备同组规则**未加**。

旧→新关键差异（节选）：

```
旧 2. 节点 label …；仅当节点有次级说明/旁注（小字注释、坑点、亮点等）时给出 note
旧 3. … style 缺省为 solid；旁注关联、弱关联或仅属说明性的连线用 dashed
新 3. 评价性短句不建节点、只作相关节点的 note：… 「坑：Tiger VNC 不支持」…「Critical Path 优化 ☆」…
新 4. …「参考」「可选」「备选」「弱引用」「跨组引用」… style:"dashed" … 例：{"label":"参考","style":"dashed"}
新 5. 弱关联不得整条丢弃 … 不得因为「不是主流程」而省略
```

## §2 单测（离线，无网络/无 key）

`tests/test_diagram_groups_ir.py` 新增 3 条，锁定 prompt 合同（防止后续被误删）：

- `test_system_prompt_activates_the_note_channel`：含 警告/坑/不支持/亮点/优化 等词、`不建节点`、
  两个锚点示例。
- `test_system_prompt_activates_the_dashed_channel`：含 参考/可选/备选/弱引用/跨组、`style:"dashed"`、
  `"label":"参考","style":"dashed"` 示例。
- `test_system_prompt_forbids_dropping_weak_relations`：含 `不得整条丢弃` 与
  `不得因为「不是主流程」而省略`。

既有 `test_system_prompt_declares_hierarchy_contract`（groups/note/style/dashed/layer/lane/cluster、
`严禁编造层次`、`[]`）保持绿。

---

## §3 LIVE 真实抽取（自跑，真实 key）

### 方法与预算

- 脚本 `/tmp/d5a_live_extract.py`：`sys.path` 指向本 worktree，**cwd = 主检出**（仅让 `eval.gateway`
  从 `.env` 读 key）；key 从未打印/导出/复制（只打印 `len`）。
- 调法：`graph2note.diagram.extract_diagram_image`（产品自身 gateway + 预算升级），图片 =
  `/tmp/spw-taudit-artifacts/originals/{01,02,02inc}.jpg`。
- 主通道 = `resolve_channel("diagram")` = **kimi / kimi-k2.6**（继承 D4 F-H：timeout 600s、首调 8000）；
  失败回落 **deepseek / deepseek-v4-flash-vision-exp**。
- **全新缓存目录** `/tmp/spw-d5a/cache`（绝不能复用 T-audit 缓存：`VlmCache` key 不含 prompt 内容，
  旧缓存会返回旧 prompt 结果）。
- 预算：每手稿每通道 ≤2 次 API 调用。实际用量见下表，均未超。

### 用量与通道

| 手稿 | 主通道 kimi | 回落 deepseek | 实际采用 |
|---|---|---|---|
| 01 | 2 次（8000→length/0；10000→length/0），505.2s | 1 次（8000→stop），16.7s | **deepseek** |
| 02 | 2 次（均 length/0），496.8s | 1 次，7.6s | **deepseek** |
| 02inc | 2 次（均 length/0），494.2s | 1 次，13.0s | **deepseek** |

**F-H 复核**：超时**不是**限制因素——kimi 两次尝试合计 ~495–505s，均在 600s 内完成；
两次都是 `finish_reason=length` 且 `content_len=0`（推理吃满预算、无正文）。
与 T-audit 诊断（旧 prompt、02、10000 tok、420s 成功）相比，本轮 3/3 空内容——可能与本轮
prompt 更长增加推理负荷有关，也可能是该模型单次采样波动（§6）。

kimi 额外尝试（01/02/02inc 各 1 次 deepseek 二次采样）合计 deepseek 9 次，见 §5。

### 交付结果（各手稿第 1 次 deepseek 样本）

**01**（19 节点 / 14 边 / 5 组 / **4 note** / **1 dashed**）：
- note：`坑：Tiger VNC 不支持`（挂 RDP/TS 节点）、`亮点：Critical path 优化 ☆`（挂调度候选）、
  `支持 Apple VNC 协议`、`Questions: …`。✅ 两个目标短句都进了 note，不再是并列节点。
- dashed：`n4 → n11`（通信层→通信源，说明性关联）✅。

**02**（9 节点 / 7 边 / 4 组 / 4 note / 0 dashed）：
- note 充分（输入/解析/输出格式等）。
- 「参考」弱关联**保留**为 `调研节点 n5 → 解析层 n7`（及 `n6→n7`）的边，未再丢弃；但本样本
  未标 `dashed`（见 §5）。

**02inc**（20 节点 / 18 边 / 2 lane 组 / 6 note / **5 dashed**）：
- dashed 含 `label=备选`×2、**`label=参考`**（n10→n11）、`label=同步`、空 label 各 1——
  「参考→dashed」在本图落地 ✅。

原始 JSON：`/tmp/spw-d5a/raw/<case>__{primary,fallback}__extract.json`；
汇总：`/tmp/spw-d5a/d5a-live-extraction.json`。

---

## §4 「不编造层次」核对（region 级）

prompt 分组规则（规则 1）未改；新样本的组都能对应手稿真实区域，成员是干净划分。与现有 live
（T-audit deepseek 样本）对照：

| 手稿 | 现有 live 组 | D5a 样本组 | 一致性 |
|---|---|---|---|
| 01 | 常用终端 / 通信层 / 任务调度 / 状态与节点图 / 通信源笔记 / 调度方案候选（4 layer+2 cluster） | 常用终端 / 通信层 / 任务拆分·路由流程 / 通信源 / 候选调度方案（5 cluster） | 区域一一对应（「任务调度」+「状态与节点图」合并）；**kind 由 layer 变 cluster**（采样波动，见 §5） |
| 02 | 顶部概览流程 / 输入层 / 解析层 / 格式化输出层 | 顶层主流程 / 调研·输入层 / 解析层 / 格式化输出层 | 4 组一一对应 ✅ |
| 02inc | 输入与解析 / 模板解析与格式化 / 解析层内部 / 格式化的输出 / 渲染层 / 输出与发布（6 组） | 笔记·手稿电子化 / 渲染（2 lane） | 6 组可映射进 2 条主流（左流程/右渲染），未编造新层 |

**结论**：无编造层次迹象；但**组数与 kind 随单次采样波动**（下一步二次采样证实）。

## §5 采样波动证据（二次样本，deepseek）

为区分「prompt 影响」与「采样波动」，对 01/02/02inc 各跑了第 2 次 deepseek 样本
（`/tmp/spw-d5a/raw2/`，仍在 ≤2 次/通道/图预算内）：

| 手稿 | 样本 A | 样本 B |
|---|---|---|
| 01 | 5 组（0 layer+5 cluster），notes=4，**dashed=1**，目标 note ✅ | 5 组（1 layer+4 cluster），notes=3，**dashed=2**，目标 note ✅（`坑：Tiger VNC 不支持`、`亮点：Critical Path 优化 ☆`） |
| 02 | 4 组，notes=4，dashed=0 | 3 组，notes=3，dashed=0 |
| 02inc | 2 lane，notes=6，**dashed=5**（含 `参考`） | 4 组（3 layer+1 cluster），notes=3，**dashed=1** |

→ **note 激活跨样本稳定**（01 三个样本都拿到两个目标短句）；**dashed 激活跨样本出现**
（01 两个样本都有，02inc 两个样本都有）；**分组计数/kind 高波动**（02inc 6→2→4），
与 T-audit 的「单次采样」限制一致，**非 prompt 引入**（规则 1 未改）。

## §6 诚实限制

- **kimi 主通道 3/3 空内容**：F-H 的 600s/8000–10000 已让调用**返回**，但 kimi-k2.6 在 8000 与 10000
  两次都 `length` 且 0 正文；交付实际全部来自 deepseek 回落。T-audit 旧 prompt 的 02 诊断曾成功，
  故「是否为本轮更长 prompt 所致」单次样本无法判定。**建议（超出本轮领地）**：kimi 增大推理预算/
  换模型，或把 diagram 默认通道改为 deepseek 视觉模型；本轮未改通道选择。
- **02「参考」未成 dashed**：两个 deepseek 样本都未产出；可能手稿该虚线/标签在 1024px 下采样后
  不可辨。「参考」**关联**已作为 `调研→解析` 边保留（未丢弃），且 02inc 已产出 `label=参考` 的
  dashed 边，故「≥1 图 dashed」达标。
- **样本量**：每手稿每通道 ≤2 次（08 baseline 预算约束），未做更多采样；未做多模型一致性。
- 未改 renderer/`_layout`/schema/配置；未合并、未自审、未 push；无 `.env`/密钥进入产物。

## §7 复现

```bash
# 单测
.venv/bin/python -m pytest -p no:warnings        # 1040 passed
# LIVE（cwd 必须是主检出以便 eval.gateway 读 .env；不 export key）
cd /Users/suyingke/Programs/OHO/graph2note
.venv/bin/python /tmp/d5a_live_extract.py        # 主 kimi→回落 deepseek，产物 /tmp/spw-d5a/
.venv/bin/python /tmp/d5a_sample_b.py            # 01/02inc 二次样本
.venv/bin/python /tmp/d5a_02_sampleb.py          # 02 二次样本
```

## §8 提交

- `0a88db0` feat(diagram): activate note/dashed channels in the extract prompt
- handoff docs commit（本文件）
