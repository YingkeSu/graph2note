# D4 — 阶段 2 复验缺陷整合修复（handoff）

Status: **ready-for-review**
分支：`dev/D4-diagram-fix`（基线 `d536f68`，未合并、未 push）
日期：2026-09-15
领地：D3 渲染/字体（`graph2note/diagrams/graphviz_renderer.py`、`matplotlib_renderer.py`、对应测试）＋
D2 布局（`graph2note/diagrams/_layout.py`、对应测试，经调度授权）＋ D1 超时/缓存（`graph2note/diagram.py`、
`graph2note/vlm.py`、对应测试，经调度授权）。

提交（`git log d536f68..HEAD`）：

| SHA | 内容 |
|---|---|
| `c89631f` | graphviz rank pinning + 三档字号 + dot -Tplain 回归测试（D3，任务 1/2/3/5） |
| `e0a5a0f` | D2 flow-isolated layer band 下沉（任务 4，F-C） |
| `c7ad341` | diagram 默认超时/预算 + cache 命中解码（任务 6/7，F-H/F-G） |
| HEAD | `c7ad341ee8869e4d3aeb44e4e3b83e4a6ce74374` |

输入证据（只读，未复制进仓库）：
`/tmp/spw-T-audit-recheck.md`、`/tmp/spw-T-vision-recheck.md`、
`/tmp/spw-T-audit-recheck-live.md`、`/tmp/spw-taudit-artifacts/recheck/{newrank-probe.json,group-band-order.json}`。

---

## §0 总览

| # | 任务 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | graphviz `newrank=true` 修 F-A/F-B/F-D | **达成，但不止 newrank**：仅 `newrank` 只修 F-A/F-B；F-C/F-D 需把 dot 的实际 rank 钉到 D2 rows | §1 |
| 2 | `dot -Tplain` 回归断言 rank == D2 rows | **达成**：4 个 golden fixture + 3 个 D1 锚点全 PASS（orientation 钉死 TB） | §2 |
| 3 | 字号三档（组>节点>note） | **达成**：graphviz 24/20/14、matplotlib 15/13/10；mpl note@720 未缓解（见 §3） | §3 |
| 4 | D2 F-C：01 锚点 3 条独立层带 + SPEC 阅读序 | **达成且不破契约**：新增「无邻接边层带下沉」规则；4 个 golden 未变（如实说明） | §4 |
| 5 | 扁平路径逐字节一致 + 全量回归 | **达成**：扁平 DOT 源逐字节 == legacy；两引擎扁平 PNG SHA == `d536f68`；pytest 1037 passed；node 2 套通过 | §5 |
| 6 | D1 F-H：kimi 主通道默认可用（超时/预算） | **达成**：`DEFAULT_TIMEOUT` 600、首调 `DIAGRAM_MAX_TOKENS` 8000；离线单测锁定 | §6 |
| 7 | D1 F-G：cache 命中丢结构图（既有 bug） | **达成**：按真实 `VlmCache` 记录解码；真实 live cache 4/4 解出 | §7 |

**未做**：合并、自审、push；无 live VLM 调用（无 key）；未改通道选择；未动 `.env`/密钥；未 `find /Users/suyingke`。

---

## §1 任务 1：graphviz 组的实际 rank（F-A/F-B/F-C/F-D）

### 处置

`graphviz_renderer.build_digraph`：
1. 分组路径加图属性 `newrank=true`（仅 `sem.groups` 非空时；扁平路径源逐字节不变）。
2. 新增 `layout_rows(layout, known_ids)`：从 D2 `layout["rows"]` 取行（过滤未知节点、丢空行）。
3. 新增 `_pin_layout_rows(g, rows)`：
   - 每行一个匿名子图 `{ rank=same; … }`，把该行全部成员钉到同一 rank（跨 cluster 需 `newrank`）；
   - 相邻行之间加一条 `style=invis` 的代表节点边（代表=该行首个节点，取自 D2 规范化 rows），
     让 dot 在没有真实边连接的层带（如零度节点层带）之间也保持 D2 推导的自上而下顺序。
4. 仅在 `sem.groups and rows` 时启用；`layout` 无 `rows`（如直接调 renderer、旧测试 layout）时不加约束。

### 为什么必须超出「只加 newrank」

T-audit 自己的 `newrank-probe.json` 显示：`newrank=true` 只把 `d2-layer`/`d2-lane` 修好；
`d2-cluster` 仍是 `设计=[1] / 调研=[0,0]`（D2 期望两者同 row 0），`anchor-01-layers` 仍是
`执行层` 与 `层间通信` 同 rank（只显 2 条带）。复现（本 worktree，pytest 之外）：

```bash
PYTHONPATH=. .venv/bin/python /tmp/d4_verify.py   # 生成脚本见 §8
# newrank 之前的实测：
#   cluster    TB newrank=True  match=False   (设计 rank 1 vs D2 row 0)
#   _ANCHOR_01 TB newrank=True  match=False   (执行层与层间通信同 rank)
# 加 rank=same + invis spine 之后：全部 match=True
```

- **F-A**（layer 成员被拆 rank）：rank pin 后 `通信层=[1,1]`、`执行层=[2,2,2]`、`层间通信=[0,0,0]` == D2 rows ✅
- **F-B**（lane zigzag 塌缩+边反向）：`d2-lane` 由 `[2,2,2]/[1,1,1]` 恢复为 `[2,4,6]/[1,3,5]` == D2 rows（7 ranks）✅
- **F-C**（01 锚点只显 2 条带）：rank pin 后 `_ANCHOR_01` 出 3 个 rank ✅（顺序由任务 4 修正，见 §4）
- **F-D**（cluster 旁注异 rank）：`d2-cluster` 两簇均落 row 0 ✅（`newrank` 单独无法修）

### 证据：`dot -Tplain` 实测（orientation=TB）

| case | D2 nrows | dot ranks | rank==row | dot stderr |
|---|---|---|---|---|
| layer | 3 | 3 | ✅ | 空 |
| lane | 7 | 7 | ✅ | 空 |
| cluster | 4 | 4 | ✅ | 空 |
| increment | 3 | 3 | ✅ | 空 |
| `_ANCHOR_01` | 3 | 3 | ✅ | 空 |
| `_ANCHOR_02` | 3 | 3 | ✅ | 空 |
| `_ANCHOR_02_INCREMENT` | 2 | 2 | ✅ | 空 |

**额外真实验证**（T-audit live 缓存 `live-extraction-deepseek.json` 的 21/10/32 节点真实 groups，
非 fixture）：三张 live IR 经 `build_digraph` 后 `dot -Tplain` 的 rank 全部 == D2 rows，且无 dot 警告：

```
01-requirements-arch          ranks==rows: True  nrows: 5  dot_ranks: 5
02-digitize-pipeline          ranks==rows: True  nrows: 4  dot_ranks: 4
02-digitize-pipeline-increment ranks==rows: True  nrows: 8  dot_ranks: 8
```

这正面回应了 T-audit live 报告 §4「F-A 复现：live 01 的 10 节点同 rank」——修后不再塌缩。

### 残留风险（诚实标注）

- invis spine 在**存在回边且 D2 行序与回边相反**的分组图上可能让 dot 形成环，dot 会自行断开
  一条边，极端情况下 rank 可能不再严格等于 D2 rows。本轮 4 fixture + 3 锚点 + 3 张真实 live IR
  均无此情形；这是「D3 服从 D2 几何」契约的已知边界，不影响扁平路径。
- rank pin 以 D2 rows 为准（架构上 D2 是几何 owner）。若评审认为 dot 应自算几何，可只保留
  `newrank=true` 并放宽测试断言——但那会把 F-C/F-D 留在缺陷状态。

---

## §2 任务 2：`dot -Tplain` 回归测试

新增于 `tests/test_diagram_render_groups.py`：

- `_dot_ranks(source, orientation)`：跑 `dot -Tplain`，解析 `node <id> <x> <y> …`，
  把坐标映射为 rank index（0 = 阅读方向首个 rank：TB 取 y 降序、LR 取 x 升序）；
  节点名带引号（如 `"win-laptop"`）已 `strip('"')`。
- `_assert_dot_ranks_equal_rows(...)`：`grouped_layout` 得 rows → `build_digraph(..., layout=..., orientation="TB")`
  → 断言 `{node: rank} == {node: row_index}` **且** `len(set(ranks)) == nrows`。
- `test_dot_ranks_match_d2_rows_for_layout_fixtures[layer|lane|cluster|increment]`（4 参数）
- `test_dot_ranks_match_d2_rows_for_d1_anchors`：直接用 `tests/test_diagram_groups_ir.py` 的
  `_ANCHOR_01/_ANCHOR_02/_ANCHOR_02_INCREMENT`（不转抄），经
  `diagram.validate_diagram_json` 复核 `ok` 后比较。
- `test_newrank_is_only_on_the_grouped_path`：扁平源无 `newrank`，分组源有 `newrank=true`。

**orientation 歧义处理**：T-audit 的 `anchor-01-layers`（无后缀）与 T-vision 的 `--TB` 差异源于
fixture 不带 `orientation` 时产品链默认（`attachments.py:155` `semantics.orientation or "TB"`）。
测试**显式传入 `orientation="TB"`**，不再依赖默认值，消除歧义。

---

## §3 任务 3：字号三档

| 引擎 | 组标题 | 节点 label | note | 备注 |
|---|---|---|---|---|
| graphviz（改后） | **24** | 20 | 14 | 严格递减；note 渲染为节点内 `<FONT POINT-SIZE=14>` |
| matplotlib（改后） | **15** | 13 | 10 | 严格递减；组标题加粗 |

`tests/test_diagram_render_groups.py::test_font_size_three_tiers_group_above_label_above_note`：
断言两引擎 `GROUP > NODE > NOTE > 0`，并锁定参考值 `(24,20,14)` / `(15,13,10)`。

**matplotlib note@720px 评估（§3 要求）**：note 档保持 10pt（未上调），因此 720px 模拟下仍约
**8.5px**，**未因组标题上调而缓解**——本轮只把组标题 13→15（@720 ≈ **12.8px**，组标题与节点区分更明显），
节点与 note 档位刻意不动以维持 15>13>10 的稳定梯度。若后续要把 note 下限抬到 ~9.4px，可将
`NOTE_FONTSIZE` 调到 11（仍满足 15>13>11）；本轮按任务给出的参考值 15/13/10 落地并如实记录该下限。
组标题 T-vision §4-①「与节点同字号」现已消除（graphviz 24>20、matplotlib 15>13）。

---

## §4 任务 4：D2 F-C（01 锚点 3 带 + SPEC 阅读序）

### 事实澄清（与任务描述略有出入）

`group-band-order.json` 里 D2 的 `d2_rows` 对 01 锚点已是 **3 个不同行**
（层间通信 row0 / 执行层 row1 / 通信层 row2）；「只显 2 条」是 **dot** 的行为（同一层带被 dot 压到
一个 rank），任务票面把两者写混了。D2 的真实缺陷只有**带序**：按「中位 depth 升序 + 组 id」排序，
层间通信(depth 0) 与执行层(depth 0) 同锚，id `g1<g3` 把执行层排在通信层(depth 1) 之前，
得到 层间通信→执行层→通信层，与 SPEC 文字/手稿阅读序相反。

### 处置（`_layout.py`，不破契约）

新增「flow-isolated layer band 下沉」规则：

- `isolated[gid] = not any(member in incident for member in members)`（`incident` = 全部有效边的端点集合）；
- entries 排序键由 `(anchor, kind, key)` 改为 `(isolated, anchor, kind, key)`；自由 depth 行取 `isolated=0`。
- **锚值（median depth）本身不变**；只把「无任何邻接边」的层带整体下沉到所有连通带之后。

结果：`_ANCHOR_01` → rows `[['n6','n1','n3','n2'], ['n4'], ['n5']]`，行序
**层间通信 0 / 通信层 1 / 执行层 2**，`nrows==3`，3 条独立层带。

### 契约校验

| 契约 | 结果 |
|---|---|
| 输入顺序不敏感 | ✅ 组/成员反转后 `grouped_layout` 逐字段相等（新测试断言；既有 `test_golden_layout_ignores_input_order` 全绿） |
| 确定性（FR-020） | ✅ 同输入两次 `json.dumps` 一致；无随机 |
| 不读 `order`/声明序 | ✅ 只用「是否有邻接边」这一图结构信号；`test_band_order_ignores_vlm_order_hint` 保持绿 |
| 既有 golden | ✅ **4 个 golden 全部零变化**（layer/lane/cluster/increment 的 layer 组都有邻接边，`isolated=0`，排序键与原逻辑逐位等价）。因此**没有 golden 需要重生成**——这是如实结论，不是漏做 |
| 01 锚点 | 新增 `tests/test_diagram_group_layout.py::test_01_anchor_isolated_band_sinks_into_spec_reading_order` 锁定行序 + shuffle 不变 |

**取舍说明**：另一种「不读声明序」的做法是把零度节点整体视为 `depth=max+1`，与本发明质等价但会改动
`anchors` 语义；选择显式 `isolated` 键，语义更窄、diff 更小、更易回退。若评审不认可该启发式，回退
`e0a5a0f` 即可（`newrank` + rank pin 仍能保证 dot 忠实呈现 D2 当时的带序，只是带序本身不合 SPEC 阅读序）。

---

## §5 任务 5：回归底线

- **扁平 DOT 源逐字节 == legacy**：`test_graphviz_ungrouped_source_matches_legacy_renderer`
  已用「手工重建的 pre-D-track source」做逐字节比较，本轮追加断言扁平源不含
  `newrank`/`POINT-SIZE`/`rank=same`。
- **扁平 PNG 逐字节 == `d536f68`**（两引擎，同 venv × 同 dot 14.1.2）：

  | 引擎 | 本 worktree SHA | `d536f68`（/tmp/spw-taudit-recheck/main-tree）SHA |
  |---|---|---|
  | graphviz | `0d58379f3c163382bb69da6ff30cb1007bae2df115565bc310b4fb6362bcac00` | 同左 ✅ |
  | matplotlib | `e836d58575916c55b0a8e8c653c0b5c5941285b008b676b389e6d27bb902dfa5` | 同左 ✅ |

  （测试以「源逐字节 + 既有 `test_matplotlib_ungrouped_png_matches_baseline_golden` + 既有
  `tests/test_diagrams.py` 两引擎 byte-determinism」锁定；未把 graphviz PNG SHA 写死进测试，
  因 dot 版本会影响 PNG 字节，源级锁更稳。）
- **全量 pytest**：`1037 passed`（基线 1027 + 新增 10；见 §8 命令）。
- **node**：`node tests/diagram_presentation.cjs` → `all assertions passed ✓`；
  `node tests/assets_rewrite.cjs` → `all assertions passed ✓`。

---

## §6 任务 6：F-H（kimi 主通道默认可用）

### 处置（`diagram.py` + `vlm.py`）

- `DEFAULT_TIMEOUT`：`120` → `600`（env `GRAPH2NOTE_DIAGRAM_TIMEOUT`，默认 600；满足任务 ≥420 参考值）。
- `DIAGRAM_MAX_TOKENS`：`3500` → `8000`（env `GRAPH2NOTE_DIAGRAM_MAX_TOKENS`）；
  仍 `< DIAGRAM_RETRY_TOKENS(10000)`，所以预算升级重试仍是真正的升级（不是同参重试）。
- `vlm._merge_visual_graph`：`timeout=max(timeout, diagram.DEFAULT_TIMEOUT)`。
  这是关键——`call_ir` 会把**文本阶段**的超时（`vlm.DEFAULT_TIMEOUT=120`）透传给图调用，
  仅改 `diagram.DEFAULT_TIMEOUT` 不足以让产品链路生效。现不论 `call_ir` 传什么，图调用至少拿到 600s。
- **不改通道选择**（仍 `resolve_channel("diagram")` → kimi-k2.6），不做 live 调用进测试。

### 数值取舍（任务要求 handoff 说明）

T-audit live 实测：首调 3500 tok 时 kimi 约 **117s** 空内容 `length`；重试 10000 tok 约 **212s** 成功；
合计约 **330s**（所以 timeout=420 可修）。本轮把首调预算抬到 8000：按同环境约 30 tok/s 估算，
首调最坏 ~267s，加重试 ~212s ≈ **479s**，故默认超时取 **600s** 留余量；若首调直接成功则只需 ~212s。
更保守的替代（保持 3500 + timeout 420）已在备选：本实现选择「更宽首调预算 + 更宽超时」，与任务
「对视觉模型取更宽默认」一致。两者均可通过 env 覆盖。

### 离线单测

- `test_extract_diagram_defaults_clear_the_budget_upgrade`：锁定 `DEFAULT_TIMEOUT>=420`、
  `3500 < DIAGRAM_MAX_TOKENS < DIAGRAM_RETRY_TOKENS`，并用 fake gateway 复现
  「首调 length+空 → 升级重试成功」，断言两次调用都带 `timeout==DEFAULT_TIMEOUT`、预算为 8000→10000。
- `test_visual_graph_stage_keeps_the_diagram_timeout_floor`：`_merge_visual_graph` 传 `timeout=30` 时，
  图调用实际拿到 `>= DEFAULT_TIMEOUT`。
- 既有 `test_extract_diagram_length_exhaustion_upgrades_once` 保持绿（动态读模块常量）。

---

## §7 任务 7：F-G（cache 命中丢结构图，既有 bug）

### 事实（`09a6d92` 起既有，非本轮引入）

- 写：`cache.put(image_path, model, json.dumps({**result, "meta": meta}))`；
  `VlmCache.put` 落盘 `{"content": <上面这串 JSON>, "meta": {}}`；`VlmCache.get` 返回**整条记录**。
- 读（旧）：`rec = json.loads(cached); return {**rec.get("result", {}), "meta": meta}`
  —— `result` 键从未写过 → 命中只返回 `meta`，`ok/nodes/edges/groups` 全丢；
  `_merge_visual_graph` 看到 `result.get("ok")` 为假 → 静默退回文本侧 IR。

### 处置

新增 `diagram._cached_result(cached)`：解析外层记录 → 取 `content` 字符串 → 再 `json.loads` 得内层
result（含 `meta`），合并外层 meta（外层优先）；兼容历史上的扁平/嵌套 ``result`` 记录。
命中分支改为 `result, meta = _cached_result(cached); meta["cached"]=True; return {**result, "meta": meta}`。

### 证据

- 用 T-audit 真实 live cache（`/tmp/spw-taudit-artifacts/recheck-live/cache/*.json`）
  直接跑 `_cached_result`：**4/4 正确解出**：

  ```
  deepseek…07d2e1c825 ok=True nodes=32 groups=6
  deepseek…a81175268b ok=True nodes=10 groups=4
  deepseek…c771830815 ok=True nodes=21 groups=6
  kimi-k2.6…a81175268b ok=True nodes=9  groups=3   ← 与 T-audit 诊断（9 节点/3 组）一致
  ```
- 回归测试 `test_extract_diagram_cache_hit_keeps_the_structure`：首次 miss 调网关，第二次命中
  （`len(calls)==1`）仍返回完整 `ok/nodes/edges/groups/caption` 且 `meta.cached=True`。

---

## §8 复现命令

```bash
cd <worktree>
# 全量
/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest -p no:warnings   # 1037 passed
# 图/布局专项
/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest \
  tests/test_diagram_render_groups.py tests/test_diagram_group_layout.py \
  tests/test_issue15_diagram.py tests/test_vlm.py -p no:warnings
# node
node tests/diagram_presentation.cjs && node tests/assets_rewrite.cjs
# 扁平路径字节对照（本 worktree vs d536f68 复核树，同 venv/dot）
PYTHONPATH=. /Users/suyingke/Programs/OHO/graph2note/.venv/bin/python /tmp/d4_flat_sha.py
PYTHONPATH=/tmp/spw-taudit-recheck/main-tree /Users/suyingke/Programs/OHO/graph2note/.venv/bin/python /tmp/d4_flat_sha.py
# dot rank vs D2 rows（4 fixture + 3 锚点 + 真实 live IR）
PYTHONPATH=. /Users/suyingke/Programs/OHO/graph2note/.venv/bin/python /tmp/d4_verify.py
```

---

## §9 诚实限制

- **无 key**：未重跑真实 VLM 抽取（F-H 修复只到「配置 + 产品链路透传」层，`live` 效果需下一轮
  在有 key 环境复核）。live IR 用了 T-audit 已落盘的缓存结果做几何验证，未产生新的模型调用。
- **10000 首调**未实测：8000 首调是外推（T-audit 只测过 3500/10000），故超时取 600 覆盖最坏序列。
- **F-C 启发式**：`isolated` 下沉规则是 D2 新增语义，仅本 worktree 的 4 golden + 3 锚点 + 3 张真实
  live IR 验证；未做广谱 fuzz（仓库内并无既有随机 fuzz 测试，任务描述的「既有随机 fuzz」在当前
  `tests/` 中不存在——如实说明）。
- **未合并/未 push**；分支 `dev/D4-diagram-fix` 指向 `c7ad341`。
