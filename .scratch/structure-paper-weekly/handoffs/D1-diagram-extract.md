# D1 — 层次化抽取与 IR 扩展（handoff）

Status: **ready-for-review**
分支：`dev/D1-diagram-extract`（基线：本地 main `916846d`，已含 SPEC §1 验收锚点更正）
作者：SPW D 轨 worker D1
日期：2026-09-14

## 结论一句话

IR 已支持 `groups` / `Node.note` / `Edge.style`（全部可选、旧 IR 双向兼容、悬空组员/坏 kind 拒绝）；VLM `SYSTEM_PROMPT` 与 `validate_diagram_json` 升级为「先识别层次→再填节点边，主标签/旁注分流」；`diagrams/infer.py` 文本侧支持显式分组声明；并完成 `extract → _merge_visual_graph → IR` 的 groups 缝合（见「领地偏差」，已获调度授权）。**live VLM 未跑**（无 key，离线 stub/fixture 证明契约）。

## 提交（每逻辑单元一个）

| commit | 说明 |
|---|---|
| `b6e8c3d` | `feat(ir): optional diagram groups, node notes and edge styles` |
| `66ab173` | `feat(diagram): hierarchical VLM contract with groups/note/style` |
| `b117801` | `feat(diagrams/infer): deterministic group declarations in text inference` |
| `99c049d` | `test(diagram): cover hierarchical IR/VLM/inference contract` |
| `4f0e0ce` | `test(diagram): offline fixtures for corrected 01/02 acceptance anchors` |
| `cbe68a0` | `feat(vlm): forward hierarchy groups through visual graph merge`（领地偏差，见下） |

`git diff --stat main...HEAD`：7 files changed, 874 insertions(+), 31 deletions(-)。

## 改动清单（按文件）

### `graph2note/ir.py`（仅 diagram/flow 区块扩展）
- 新增 `DiagramGroup(id, label, kind∈{layer,lane,cluster}=cluster, nodes=[str])`；`label` 必填（对齐 SPEC §1 原文）。
- `Node.note: Optional[str] = None`；`Edge.style: Literal["solid","dashed"] = "solid"`。
- `_DiagramMixin.groups: list[DiagramGroup] = []`，`DiagramBlock`/`FlowBlock` 均继承。
- `_DiagramMixin` 增加 `model_validator(mode="after")`：组 id 唯一、每个成员 id 必须存在于 `nodes[]`（悬空即 `IRValidationError`）。分组**不参与**任何拓扑/边校验。
- `__all__` 增加 `DiagramGroup`。

### `graph2note/diagram.py`
- `SYSTEM_PROMPT` 升级：先判层次→`groups`；`kind` 语义（layer/lane/cluster）；members 按阅读顺序；`note` 只放次级旁注、禁止把主标签塞进 note；`style` 缺省 solid、弱关联用 dashed；普通说明/目录/旁注**不得臆造为节点**；**无层次时 `groups` 合法为空 `[]`，严禁编造层次**。
- `validate_diagram_json`：保留既有严格性（唯一 id、边引用存在、无自环、≥1 节点、`error`→no_flow），新增 `note`（trim 后空→省略）、`style`（非法→malformed）、`groups` 校验（组 id 唯一、`kind` 枚举、成员必须存在）。
- 新增 `GROUP_KINDS`、`_clean_note`、`_normalize_groups`。
- `extract_diagram_image` 结果新增顶层 `"groups"` 键；预算升级重试/空内容不重试/降级 verdict 语义**完全不变**。

### `graph2note/diagrams/infer.py`
- 新增分组声明语法：`[layer|lane|cluster] <label>: <name1>, <name2>`（支持 bullet、`：`、`、`、`|` 分隔）。
- 新增 `is_group_decl` / `parse_group_decl` / `is_graph_source_line` / `infer_graph_from_lines`（返回 `nodes, edges, groups`）。
- `relation_lines` / `relation_run` / `arrow_flow_block` / `detect_diagram_markdown` 识别分组声明；`arrow_flow_block` 输出含 `groups`。
- **无声明即空 groups（不编造）**；成员按 node 出现顺序去重排序；声明顺序决定 `g1..gN`。
- `infer_flow_from_lines` 保持原 2-tuple 返回（向后兼容），内部委托 `_relations_to_graph`。

### `graph2note/vlm.py`（领地偏差，授权）
- `_merge_visual_graph` 的 `kept.append({...})` 增加一行 `"groups": result.get("groups", [])`。

### 新增测试
- `tests/test_diagram_groups_ir.py`（37 用例）：IR 兼容/拒绝、prompt 契约、validator、stub 抽取路径、infer 分组、修正后验收锚点 fixture。
- `tests/test_diagram_groups_pipeline.py`（2 用例）：extract→merge→IR 全链 groups 存活；旧 extractor 缺 `groups` 时回退空列表。
- `tests/taxonomy.py`：登记两个新测试文件（`diagrams` 模块）；**append-only，未改任何既有行**（元测试要求新文件必须登记）。

## 决策记录（brief 要求逐条说明）

1. **序列化策略 = 显式空值（非省略）**。理由：`dumps_ir` 现为 `model_dump_json(indent=2)`，本来就显式输出全部默认值（`source: null` 等）；保持全局序列化行为不变比引入 `exclude_defaults` 更安全（后者会顺带省略 `version`/`document_type` 等既有字段，影响面大且非本任务范围）。效果：新 JSON 显式带 `groups: []`、`note: null`、`style: "solid"`；旧 JSON（无这些键）照常加载为默认值，双向兼容。
2. **`validate_diagram_json` 返回形状改为 `(dict, verdict)`**，dict 含 `nodes/edges/caption/groups`。原为 3-tuple `((nodes,edges,caption), verdict)`；只有在 `diagram.py` 内部一处调用（已同步更新），全仓库无其他调用者、无测试直接依赖。选 dict 是为后续扩展不再改元组长度。**若 reviewer 认为需保 3-tuple 兼容，请打回，我可改为新增 `validate_diagram_json_full` 并保留旧签名。**
3. **抽取侧确定性排序写死**：`groups[].nodes` 视为集合 → 去重后按节点在 `nodes[]` 中的出现顺序排序；`groups` 列表本身**保留模型/声明顺序**（层次带的自上而下阅读顺序是语义，不是集合）。此规则已在 `diagram._normalize_groups` 与 `infer.infer_graph_from_lines` 两处实现并测试；D2 的 `_canonical` 若需按 id 全序，自行处理（SPEC 允许 D2 加 `order_hint`）。
4. **不给 `DiagramGroup` 加 `order_hint`**：阅读顺序由抽取顺序承载，D1 不预设 D2 契约；若 D2 实测必须有显式层序，再按 SPEC 允许方式补。
5. **文本侧 groups 需显式声明**：仅当转录文本出现 `[kind] label: names` 才产生 groups；不基于节点名做任何启发式聚类（遵守「严禁编造层次」）。当前 stage-1 转录实际不会产出该语法 → 默认仍是扁平 flow（诚实限制，见下）。
6. **`DiagramGroup` 未加 `extra="forbid"`**：与既有 `Node`/`Edge`/各 block 一致（块级 extra 忽略、根级 extra 拒绝），即 SPEC「extra 拒绝策略不变」。已加回归测试锁根级 extra 仍拒绝。

## 领地偏差（调度已授权，reviewer 重点核这一处）

- **文件**：`graph2note/vlm.py`，唯一改动是 `_merge_visual_graph` 内 `kept.append` 增加一行 groups 透传（+4 行注释，共 +5/-0），无其它改动（见 `git diff main...HEAD -- graph2note/vlm.py`）。
- **授权**：调度 `graph2note-9` 2026-09-14 明示裁定 (a) 授权延展，理由：vlm.py 本轮无 owner，不补则 live 链路 groups 恒丢失、阶段2 几何复验（groups>0）必挂。
- **必要性 stub 复现证据**：未改 vlm.py 前，用 stub `extract_diagram_image` 调 `vlm._merge_visual_graph`，产物 flow block keys = `['caption','edges','nodes','orientation','source','type']` —— **无 groups**，IR `groups == []`；`node.note`/`edge.style` 因 nodes/edges 整体透传而存活。补丁后 `flow["groups"] == result["groups"]`，IR groups 正常。
- **约束遵守**：只此一处最小 diff；未顺手重构、未动无关行。

## 测试证据（离线，命令可复跑）

```
python -m pytest -p no:cacheprovider          # 全量
# 920 passed, 6 warnings in 122.29s

python -m pytest tests/test_diagram_groups_ir.py tests/test_diagram_groups_pipeline.py -p no:cacheprovider
# 39 passed
```

覆盖点：
- **pydantic 兼容**：旧 JSON（无 groups/note/style）加载默认值；新 JSON dump→load 完全等价（`model_dump` 相等）。
- **拒绝用例**：悬空组员、重复组 id、坏 kind、缺 label、坏 style、根级 extra；`validate_diagram_json` 侧同样的非法输入→`(None,"malformed")`；**自环仍 malformed**；空 groups 合法。
- **prompt 契约**：`SYSTEM_PROMPT` 含 groups/note/style/dashed/layer/lane/cluster 与「严禁编造层次」「[]」；stub `_post` 捕获实际 system message 断言新文本生效。
- **解析路径**：stub gateway 返回含 groups/note/dashed 的 JSON → `extract_diagram_image` 结果正确；无层次→`groups==[]`；悬空→`verdict=="malformed"` 降级。
- **全链缝合**：`extract_diagram_image`(stub `_post`) → `vlm._merge_visual_graph` → `parse_ir_json` → `ir.load_dict_as_ir`，groups/note/style 全部存活；旧 extractor 无 groups 键→IR `groups==[]`。
- **确定性**：同一语义成员乱序→相同 groups；文本侧声明顺序→`g1..gN`。
- **验收锚点 fixture（修正后 SPEC §1）**：01 → ≥2 个 `layer`（macmini/macbook/windows laptop 归层），「亮点：Critical Path 优化 ☆」只作 `note`、不进任何节点 label；02 → 主链 solid 有向 + 旁注 `note`（含「设计」）+ `dashed` 弱关联；02-increment → 两个 `lane` 组、成员互斥且覆盖左右两侧。

## 诚实限制

1. **live VLM 未跑**：本环境无 key，`extract_diagram_image` 的真实模型行为（尤其 01/02 的 groups 判别质量）**未验证**；只以 stub/fixture 证明「契约与解析路径正确」。live 效果需在有关键的环境复验（T-audit 阶段2 / T-vision）。
2. **文本侧 groups 实际不触发**：stage-1 的 Markdown 转录不会主动输出 `[layer]…:` 语法，故生产文本兜底路径默认仍为扁平 flow（groups 空）。这是「能力到位、信号缺失」，非遗漏；若要激活需 stage-1 提示词协同（不在 D1 领地）。
3. **`validate_diagram_json` 返回形状变更为破坏性扩展**（见决策 2），已提供回退方案。
4. **未改渲染/布局**：`groups` 目前只进 IR；graphviz `cluster` 子图 / matplotlib 分组框、布局分层由 D2/D3 实现。当前渲染器忽略 `groups`（旧行为不破）。
5. **未加 `order_hint`**，层序语义由 groups 数组顺序承载；D2 若做 `_canonical` 按 id 排序需自行决定是否保留/补 order_hint。
6. `tests/taxonomy.py` 属测试基础设施、非 D1 领地，但为满足「全量 pytest 绿」的元测试强制登记，仅 append 两行。

## 交付 / 待办交接

- D2 可消费：`FlowBlock.groups`（`id/label/kind/nodes`）、`Node.note`、`Edge.style`；建议布局按 `kind=layer` 同层带、`lane` 同列、`cluster` 邻接。
- D3 可消费：graphviz `cluster_*`、matplotlib 分组背景框 + 组标题、`dashed` 边、`note` 小字；SPEC 要求 group label 字号 ≥ note 字号。
- reviewer 请重点核：① vlm.py 单行缝合与 stub 全链测试；② `validate_diagram_json` 返回形状决策是否接受；③ 序列化「显式空值」决策；④ 修正后验收锚点 fixture 是否与 SPEC 一致。
