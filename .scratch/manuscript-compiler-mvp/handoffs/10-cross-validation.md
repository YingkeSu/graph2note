# Handoff 10 — 交叉验证引擎 (Cross-Validation Engine, issue 10)

> 分支 `dev/10-cross-validation`（自 `origin/main`）。**已交付**。状态 in-review。
> 本文档记录事实、产物、验证方法与潜在 follow-up；勿留已过时段落。

## 交付物

- **新包 `graph2note/verify/`**（9 模块）：
  - `text.py` —— 块文本归一化（折叠空白/大小写，保留 CJK 与全角字形）+ `block_similarity`（同类型 block 才能匹配，difflib ratio）。
  - `model.py` —— `DiffBlock`/`BlockDiff`/`DuplicateGroup`/`CrossValidationReport`（可 `to_dict()` 可逆）；三类分歧常量 `CONSISTENT`/`ONE_SIDE`/`CONFLICT`。
  - `diffing.py` —— **纯函数** `diff_documents(a, b) -> BlockDiff`。两段算法：① 精确内容匹配（order-tolerant，先按 normalized_key 匹配一致块）；② 对剩余块做 Needleman–Wunsch 全局对齐 → 基于 sim 分出 `conflict`（对齐但文本打架）/`one_side`（只在一侧出现）。顺序差以 block 级 note + `order_changed` 上报，不刷屏。
  - `duplicates.py` —— 文档内近重复块检测（union-find + `DUP_THRESHOLD=0.85`）。
  - `engine.py` —— `cross_validate(image, model_a, model_b, ...)` 编排双模型；`run_model` 复用 `vlm.call_ir` 固定网关策略（stable session/direct output/1024 降采样/hard timeout）；`verify_primary_against_second` 供 router seam 消费。**`max_tokens` 显式 = 10000**（网关文档：3500 会被 reasoning 耗尽 → `content` 为空，这是本次实跑踩到的坑）。
  - `report.py` —— `to_json`/`to_markdown`（按三类聚合表格，人工可读；raw 冲突对另节）。
  - `cli.py` —— `verify <image> [-o outdir] [--model-a] [--model-b] [--cache-dir] [--no-preprocess]`。
  - `__init__.py` 导出；`pyproject.toml` packages 补 `graph2note.verify`。
- **Router 缝接通**：`RecognitionRouter.verify_second_model` 基类保持 `NotImplementedError`（接口契约）；`RouteARouter` **实现**该缝（记 `_image_path`，新增 `second_model` 参数），调用 `verify_primary_against_second` diff 已识别文档 vs 第二模型新解析。`RouteB.verify_second_model` 未实现。
- **CLI**：`graph2note verify --help` 已接入 `cli.main` 派发。
- **测试**：`tests/test_verify_diff.py`（9，四类 fixtures + 近重复正/负 + 聚合不刷屏 + 空文档）；`tests/test_verify_engine.py`（7，双模型一致/单模型降级/双模型全失败/序列化/分歧率口径/router 缝 E2E）。全部离线（注入 runner），无网络。`test_router.py` 缝断言已更新（基类仍 NotImplemented，RouteA 实现、缺 image/second 时报错）。
- **实跑数据**（AC5）：`scripts/verify_manual.py` → `out/10/report.json` + `out/10/summary.md`（含观察结论）；缓存 `out/10/cache/` 已 gitignore。

## 关键决策

- **分歧率口径**：`分歧率 = (ONE_SIDE + CONFLICT) / 全部对齐块 * 100`；报告含每逢量的口径定义。
- **顺序差用内容对齐、不刷屏**：先把 identical normalized-key 块归 `consistent`，顺序差只以 `order_changed` + note 上报（SPEC「分歧极多→按块聚合」）。
- **`max_tokens` 必须 10000**（继承 03 的 `DEFAULT_MAX_TOKENS=3500` 会导致 reasoning 耗尽、`content` 空）。`run_model`/`cross_validate` 显式传 `max_tokens=10000`，不动 `vlm.call_ir` 默认值。
- **降级语义**：单模型失败 → `verified=False` + `note` 标「未验证:xxx失败/超时，降级为单模型结果，不阻塞出稿」；双模型全失败也有干净路径。降级时把存活方全部块标为 one_side（不做虚假 cross-diff）。

## 验证

- `./.venv-spike3/bin/python -m pytest tests/ spike3/tests/ -p no:cacheprovider` → **162 passed**（10.99s）。
- `graph2note verify --help` 派发正常。
- 实跑（2 评估图 × 双模型，共 4 次 live 调用）:两图均 ✅ 双模型完成；分歧率 100% / 91.67%。
- 实跑踩坑：默认 3500 max_tokens 两模型均 `finish_reason: length`、`content` 空 → 改 10000 后 `finish: stop`、正常出 IR。

## 实跑观察（记录在 summary.md）

两模型**语义内容大幅一致**，但块粒度不同（glm 把多项指令合并为一个 `list`，deepseek 拆成多个 `paragraph`），故块级 one_side 偏多 → 分歧率高。属**结构性（segmentation）差异，非事实冲突**。调优方向记录于 summary.md（list/paragraph 合并规范化、结构 vs 内容分歧分开计、选型以事实一致性为主）。

## AC 勾销

- [x] `verify <image>` 产出三类分歧报告（json + 可读 md）
- [x] 一致/单侧/不一致三类在构造的 fixtures 上各有点亮用例
- [x] 单模型失败路径降级为「未验证」标注，端到端不失败
- [x] 文档内重复块检测有正例与负例测试
- [x] 双模型对评估集样本的分歧率数据有记录（`out/10/`，供选型与调优）
- [x] diff 引擎测试全部离线（golden fixtures），CI 无 live 调用

## 边界 / 未做

- 不改 issue 03 解析管线文件（engine 复用其 IR/`vlm`/`preprocess`，router 只加缝实现）。`vlm.call_ir` 默认 `max_tokens` 仍为 3500（留给 03 决策），本包显式传 10000。
- 未做 list/paragraph 合并规范化（见观察，留作后续调优）。
- 未接入 issue 06 的 UI 展示位（06 解锁后可消费 `CrossValidationReport`）。
- 分歧率基线不会像准确率那样「越高越好」——当前高分歧被解读为结构性差异，选型结论由维护者/01 定夺。

## 潜在 follow-up（非本期范围）

1. 结构/内容分歧分离 + list 合并预处理，降低结构性噪声；
2. 分歧率阈值与「高冲突」触发人工复核的门槛；
3. 把 `verify` 结果联到 notes-organizer 溯源与 issue 06 展示位；
4. 扩大评估集（30–50 张，SPIKE 规划）做选型定量对比。