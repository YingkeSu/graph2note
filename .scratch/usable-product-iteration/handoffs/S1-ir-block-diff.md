# Handoff S1 — IR 块级 diff 引擎（DiffReport 纯函数）

Branch: `dev/s1-ir-block-diff` · Issue: `.scratch/usable-product-iteration/issues/S1-ir-block-diff.md` · Status → in-review

## 1. 一句话结论

Document IR 层块级语义对比引擎已交付：`diff_ir(ir_a, ir_b) -> DiffReport` 是纯函数（零模型调用、
零 IO、同输入同输出），输出块级 `added/removed/modified/moved/unchanged` 操作序列（含相似度分）、
按类型/操作汇总统计、显式阈值的 `unchanged/minor/major` 整体判定，以及双向块定位（`BlockRef`，
供 S3 高亮跳转）。新增只读 CLI `graph2note diff <doc_id>` 作为 S3 之前的主要人审消费面。已用真实
用户库（43 篇、51 组相邻版本）跑通，无崩溃、确定性一致、块定位逐条校验通过、库文件零改动。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/semantic/__init__.py`（新） | 对外稳定面：`diff_ir`、`DiffReport`/`DiffSummary`/`BlockChange`/`BlockRef`/`TypeCounts`、`MODIFIED_THRESHOLD`、`MINOR_MAX_DENSITY` |
| `graph2note/semantic/text.py`（新） | 纯文本/结构 helper：NFKC + 大小写/空白规范化、ASCII 词 + CJK 一元/二元 token、Sørensen–Dice token 重叠率、`content_key`（严格内容同一性）、按类型的结构 token（公式 latex+inline、图表 nodes/edges/caption/orientation、表格 headers/rows、列表 ordered、代码 language、图片 alt+src basename）、`preview` |
| `graph2note/semantic/diff.py`（新） | 引擎与报告模型：按块类型分组 → 精确内容匹配（顺序无关）→ 阈值化贪心相似度匹配 → LIS 移动检测 → 分类与汇总；`MODIFIED_THRESHOLD = 0.5`、`MINOR_MAX_DENSITY = 0.25` 显式常量 |
| `graph2note/semantic/cli.py`（新） | 只读版本解析与 IO（`resolve_version`、`load_version_ir`、`version_ir_path`）+ 人类可读/JSON 渲染 |
| `graph2note/cli.py` | 新增 `diff` 子命令分发（4 行） |
| `pyproject.toml` | `packages` 登记 `graph2note.semantic` |
| `tests/test_semantic_diff.py`（新，24 项） | 纯引擎：AC1/AC2/AC3/AC5 全部夹具与规则表 |
| `tests/test_semantic_diff_cli.py`（新，12 项） | CLI：版本选择、人类/JSON 输出、边界与只读性 |
| `tests/taxonomy.py` | 登记 `test_semantic_diff → ir`、`test_semantic_diff_cli → cli`（含 integration 集） |

## 3. 关键决策

- **两段式匹配而非单一序列对齐**：先按块类型分组；组内先做「内容严格相同」的顺序无关匹配
  （A 块配最近位置的空闲 B 块），再做「相似度 ≥ 阈值」的确定性贪心匹配（按 `(-相似度, index_a,
  index_b)` 排序，可复现）。顺序对齐无法识别“移动”，而顺序无关匹配会把纯重排变成 moved 而非
  一片 removed+added。
- **`moved` 用 LIS（最长递增子序列）判定，而非“绝对下标变化”**。若按绝对下标判定，文档头部
  插入一个块会把后面所有相同块误报为 moved。改为：匹配对按 A 序读出 B 位置序列，落在 LIS 之外
  者才确实需要被搬动，判定为 `moved`；纯插入/删除不产生 moved（有专测
  `test_pure_insertion_does_not_mark_followers_moved`）。交换两块时按最少移动数只报 1 个 moved。
- **严格内容同一性 vs 渐变相似度分离**：`content_key` 决定 `unchanged`/`moved`（同类型 + 规范化
  内容 + 结构标志）；`block_similarity` 决定 `modified` vs `removed+added`。公式/图表用结构字段
  token（latex、inline、nodes/edges/caption/orientation 等），不靠文本长度。
- **`source` 字段被排除出内容与相似度**：diagram/flow 的 `source` 是指向版本资产目录的溯源路径，
  纳入会把每次重解析都误报为修改（真实数据里 diagram 多为纯黑页占位）。
- **变更密度分母 = `blocks_a + blocks_b`**：保证密度落在 `[0, 1]`（若用 `max(a,b)`，整篇替换会得到
  2.0 的“密度”，可读性差）。判定规则显式：`changed==0 → unchanged`；`density <= 0.25 → minor`；
  否则 `major`。
- **相似度阈值精确可测**：`"a b c d"` vs `"a b x y"` 的 Dice 恰为 `0.5 == MODIFIED_THRESHOLD`
  （判 modified），`"a b c d"` vs `"a x y z"` 恰为 `0.25`（判 removed+added）；monkeypatch 抬高
  阈值令前者翻转为 removed+added，证明分类完全由常量驱动。
- **引擎零 IO，IO 全在 CLI**：`semantic` 包内只有 `cli.py` 触碰文件系统，且只读。
- **未改 `store.py`**：版本目录布局由 `semantic/cli.py` 的 `version_ir_path` 按 store 既有契约
  拼接，避免与 R1/A1 等并行 issue 争用共享文件（`get_document` 只给最新版 `ir_path`）。

## 4. AC 逐条证据

| AC | 证据 |
|---|---|
| 1 纯函数 `diff_ir`，不触网/不读文件/确定性 | `test_same_input_same_output_and_snapshot_stable`（两次 `model_dump()` 全等、JSON 往返稳定）、`test_engine_does_no_file_io`（monkeypatch `builtins.open` 抛错仍正常出报告）；真实库重复运行 2 次 `model_dump()` 全等（见 §5） |
| 2 fixture 覆盖：全同/全换/标题改/段落移动/公式改/图表增删/空 IR | 全部 7 类各有专测并断言 op 与 block_type：`test_all_identical_is_all_unchanged`、`test_all_replaced_is_removed_plus_added_no_modified`、`test_heading_edit_is_modified_heading`、`test_paragraph_move_is_moved_not_removed_added`、`test_formula_edit_is_modified_formula_via_structure`、`test_diagram_added_and_removed`（+ `test_diagram_modification_is_structural`）、`test_empty_ir_edges`（空/空、空↔非空两向） |
| 3 阈值上下边界分别判 modified 与 removed+added | `test_similarity_at_threshold_is_modified_below_is_removed_added`（0.5 判 modified、0.25 判 removed+added，且断言 `similarity == 0.5`）、`test_threshold_is_the_only_boundary`（抬高阈值后 0.5 对翻转为 removed+added） |
| 4 真实数据验证（人审记录） | 见 §5：真实库 `doc-9ddad73fc1` 相邻两版 diff 人审可读；19 条变更的 `BlockRef` 逐条回读 IR 校验类型+preview 全对；库文件哈希前后完全一致（只读）；全库 51 组相邻版本 diff 0 失败 |
| 5 汇总统计与整体判定独立单测（规则表驱动） | `test_verdict_rule_table`（7 行表：identical/both-empty/one-replaced-of-five/one-modified-of-two/one-modified-of-three/full-replace-two/empty-to-two → changed/density/verdict）、`test_verdict_boundary_at_minor_max_density`（0.25 边界两侧）、`test_summary_by_op_and_by_type_counts_are_consistent`（by_op、by_type 与 changes 交叉计数一致，`total_blocks = blocks_a + blocks_b`） |
| 6 CLI 便捷入口，人类可读摘要 | `test_cli_diff_latest_vs_prev_human_readable`、`test_cli_diff_json_is_a_structured_report`、`test_cli_diff_version_selectors`（`--versions 0 1` / `prev latest` 与默认等值）、`test_cli_diff_list_versions`、`test_cli_diff_rejects_bad_selector`、`test_cli_diff_unknown_document`、`test_cli_diff_single_version_is_safe`、`test_cli_diff_all_flag_includes_unchanged`、`test_cli_diff_is_read_only` |

## 5. 真实数据验证（AC4，人审）

命令（只读，零模型调用）：

```bash
uv run python -m graph2note.cli diff doc-9ddad73fc1 --versions 1 2
# 库：~/Library/Application Support/Graph2Note/storage（43 篇）
# A=v1789151206829-1 (2026-09-12T02:26:46, glm-5.3-flash, 16 块)
# B=v1789176022125-2 (2026-09-12T09:20:22, deepseek-v4-flash-vision-exp, 10 块)
```

输出（节选，完整 19 条变更）：

```
doc: doc-9ddad73fc1  "C28"
A: v1789151206829-1  created=2026-09-12T02:26:46  blocks=16
B: v1789176022125-2  created=2026-09-12T09:20:22  blocks=10
verdict: major   changed=17/26   density=0.6538
by op: added=3 removed=9 modified=5 moved=0 unchanged=2
by type:
  formula      removed=3
  heading      removed=4
  list         added=3 removed=2 modified=5
changes:
  [added] list  — -> #1
      B: 香农编码
  [removed] heading  #1 -> —
      A: 1. 香农编码
  [modified] list  #2 -> #2  sim=0.8642
      A: 对S的某一排列，满足 $P_1 \geq P_2 \geq \dots \geq P_n$ | 取 $i, s.t. ...
      B: $x$ 的某一排列，满足 $p_1 \geq p_2 \geq \dots \geq p_n$ | 取 $l_i, s.t. ...
  [modified] list  #6 -> #6  sim=0.9016
      A: ①：将n个概率降序排列 | ②：分成概率和相近两组，赋0/1 | ③：对组内重复操作 | 即时，唯一可译
      B: ①. 按概率降序排列 | ②. 分成概率和相同两组，赋 0/1 | ③. 对组内重复操作 | 即时，唯一可译
  ...
```

人审结论：报告可读——`verdict/density/by op/by type` 一眼可见这一版主要是删除标题/公式、改写列表；
`modified` 的相似度分（0.86 / 0.90 / 0.64 / 0.57）与块内容差异程度相符。块定位准确：脚本对全部 19
条变更的 `block_ref_a`/`block_ref_b` 回读对应版本 `ir.json`，逐一断言 `block_type` 相等且
`preview == text.preview(blocks[index])`，结果 `refs checked: 19, bad: 0`。

附加鲁棒性/只读证据（脚本输出）：

- 确定性：同输入两次 `model_dump()` 全等 → `deterministic: True`
- 只读：运行 `diff --json` 与 `diff --list` 前后，文档目录所有文件 SHA-256 完全一致 → `read-only (byte-identical): True`
- 全库：对 43 篇中所有多版本文档的每组相邻版本跑 diff → `adjacent-version diffs ok: 51 fails: 0`

## 6. 与 S2 / S3 的接口稳定性（后续衔接）

`DiffReport` 的 JSON 形状即为下游契约（pydantic `model_dump()`，字段稳定、无 IO）：

- **S2（版本链摘要）**：对版本链相邻版调用 `diff_ir(a, b, label_a=vid_a, label_b=vid_b)`，把
  `report.summary`（`verdict`/`changed_blocks`/`change_density`/`by_op`/`by_type`）直接作为每版
  diff 摘要；`report.changes` 提供块定位。S2 只需要 `graph2note.semantic` 的公开导出，不必触
  `diff.py` 内部。
- **S3（对比视图高亮/跳转）**：每个 `BlockChange` 携带 `block_ref_a`/`block_ref_b`，其中
  `index`（0-based，对应渲染顺序）+ `block_type` + 确定性 `anchor`（`block-{index}`）+ `preview`
  足以做块级归属、并排高亮与“点击跳到当前版本对应块”。S3 摘要条的按类型计数直接取
  `summary.by_type`，与 `summary.by_op` 数字同源（同一 `changes` 列表推导，不存在第二套统计）。
- **阈值/判定可配置面**：`MODIFIED_THRESHOLD`、`MINOR_MAX_DENSITY` 为模块级常量，S2/S3 不应重新
  定义；如需按用途覆盖，建议在调用侧显式传参而不是改默认（当前签名未开放参数，保持契约简单）。
- **已知边界**：`moved` 仅对“内容完全相同的重排”判定；既改内容又移位的块归 `modified`
  （单一 op 字段，优先级：content 变化 > 位置变化）。S3 若要展示“移动且修改”，可用
  `similarity < 1.0` 且下标不连续来启发式识别，不需要改引擎。

## 7. 如何运行

```bash
uv run pytest tests/test_semantic_diff.py tests/test_semantic_diff_cli.py   # 36 passed
uv run pytest -m "ir or cli or meta"                                        # 56 passed
uv run pytest                                                               # 516 passed
uv run python -m graph2note.cli diff <doc_id> --list
uv run python -m graph2note.cli diff <doc_id> --versions latest prev
uv run python -m graph2note.cli diff <doc_id> --versions 0 2 --json
```

## 8. 未尽事项 / 建议

1. **匹配最优性**：第二段为确定性贪心（非全局最优分配）。文档规模（真实库单版 ≤ ~50 块）下足够，
   且顺序无关首段已吸收绝大多数相同块；若未来出现长文档歧义匹配，可换 Hungarian/最小代价流，
   接口不需要变。
2. **`moved` 与 `modified` 的复合情况**：见 §6 已知边界。若 S3 明确要区分，可在不破坏现有字段的
   前提下新增 `moved_and_modified` 布尔（当前未做，避免过度设计）。
3. **CLI 版本选择**：支持整 id / 唯一前缀 / 0-based 下标 / `latest`/`prev`。未做交互式选择器；S3 的
   UI 会直接消费 S2 的版本链 API，不依赖本 CLI。
4. **文本相似度**：当前 token 重叠对中文用一元+二元、英文用词；未做同义词/繁简/词干。若审阅发现
   改写型修改阈值偏敏感/偏保守，调 `MODIFIED_THRESHOLD` 即可，规则表测试会锁住行为。
5. **`total_blocks` 语义**：定义为两侧块数之和（保证密度 ∈ [0,1]）。若下游希望“相对单版块数”的
   密度，可在 S2/S3 侧用 `changed_blocks / max(blocks_a, blocks_b)` 另算，不改变引擎契约。

## 9. 相关文件

- 实现：`graph2note/semantic/{__init__,text,diff,cli}.py`、`graph2note/cli.py`、`pyproject.toml`
- 测试：`tests/test_semantic_diff.py`、`tests/test_semantic_diff_cli.py`、`tests/taxonomy.py`
- 上游：`.scratch/usable-product-iteration/ISSUE-DRAFT.md` §2.3、`issues/S2-evolution-anchoring.md`、`issues/S3-version-diff-ui.md`
- 相关既有实现（未复用、仅供对照）：`graph2note/verify/diffing.py`（双模型交叉验证的 3 分类块 diff）
