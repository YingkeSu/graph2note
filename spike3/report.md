# Spike 3 — 流程图语义提取 + matplotlib/graphviz 重建可行性

> 结论将交由 issue 05（Diagram 渲染器）消费。所有 LLM 调用仅出现在手工脚本
> `gateway.py`；`pytest` 全离线；每一步的响应已缓存到 `cache/`。
> 版本：2026-09-08 · worktree `graph2note-4` · 分支 `dev/04-spike3-diagram-rebuild`

## 1. 目标与方法

验证 MVP 闭环：**手稿图 → VLM 抽取结构化 nodes/edges → 确定性渲染**。

- 样本：10 张合成手写风流程图 `S01..S10`（已知真值，**标注为合成**）+ 2 张真实
  手稿图 `R01/R02`（`test-images/`，无真值，仅定性）。因真实手稿尚在 HITL 收集，
  以合成样本做定量评分，真实图为定性辅助 —— 不阻塞。
- 抽取：`glm-5.3-flash` 与 `deepseek-v4-flash-vision-exp`，强制输出严格 JSON
  `{"nodes":[{"id","label"}],"edges":[{"from","to","label"}]}` 或
  `{"error":"no_flow_extractable"}`（无 Markdown 围栏，中文标签原样保留）。
- 评分：以**标签对**骨架比对（ID 由模型自行编号，与真值不同；样本标签唯一），
  归一化全/半角标点。指标：edge 精确率/召回率、节点数符合、标签命中。
- 渲染：matplotlib 手写分层布局 vs graphviz(dot)，判据：节点重叠、连线交叉、
  中文渲染（无豆腐块）、逐字节可复现（FR-020）。

## 2. 抽取结果（成功率与失败模式）

| 模型 | 抽取成功（可解析 Diagram） | 结构精确率 (S01–S09, n=9) | 结构召回率 (n=9) |
|---|---|---|---|
| `glm-5.3-flash` | **10/12 (83%)** | 0.86 | 0.80 |
| `deepseek-v4-flash-vision-exp` | 10/12 (83%) | **1.00** | **0.94** |

按样本明细：

- **glm-5.3-flash**：S01–S09 全部正确；`R01`（真实大图 ~800KB）完整抽出
  5 节点 / 6 边（含回边、中文多词标签）。失败：`S10`、`R02` = **空内容**（返回 200 但
  `content` 长度为 0）。结构瑕疵：`S02` 链式边整组丢失（P/R=0）、`S04` 缺一条合并边、
  `S07` 一条合并边方向反、`S09` 少一条回边且边标签错配。
- **deepseek-v4-flash-vision-exp**：S01–S09 **全部精确率 1.00**（结构更准）；
  `S10` 丢了一个节点（5/6，P=0.40 R=0.33）。失败：`R01`、`R02`（两张真实大图）
  **均返回空内容**。

**典型失败模式**（笔记到报告）：
1. **空内容**（http 200、`content` 长度 0，`reasoning_content` 可能为空）—— 发生在
   大图/复杂图，两模型都观察到；是第二根因。
2. 链式或回边**整体丢失**、**漏边**（召回损失）。
3. **合并边方向反** / **边标签错配**（精确率损失）。
4. 节点数偶发少取（deepseek S10）。
5. 标点全/半角差异（纯评分归一化问题，非模型错误）。

**触发降级（crop）占比**：空内容/无法解析 = 4/24（两张真实大图×2 模型 + S10/R02 glm）
≈ **17%**，即约每 6 次抽取约 1 次走「裁剪原图嵌入」降级路径。

## 3. 渲染工具链对比（matplotlib vs graphviz）

| 判据 | matplotlib（手写分层布局） | graphviz(dot, rankdir=TB) |
|---|---|---|
| 确定性（FR-020，同一语义两次渲染逐字节一致） | ✅ 10/10 | ✅ 10/10 |
| 节点重叠（10 合成图） | 3 个（S05=2, S09=1，均在**环上回边**） | **0** |
| 连线交叉（10 合成图） | 0 | 0 |
| 中文渲染 | ✅ 无豆腐块 | ✅ 无豆腐块（fontconfig 命中 Arial Unicode MS） |
| 输出体积（PNG） | 12–27 KB | 10–33 KB |
| 依赖 | 纯 Python（matplotlib/Pillow） | 需系统安装 `dot` 二进制 |

结论：两方案都满足 FR-020 确定性；**graphviz 布局质量显著更优**（自动布局对环/回流
零重叠、零交叉），中文正常；代价是 `dot` 系统依赖。matplotlib 手写分层布局在无环图上
同样零重叠零交叉，纯 Python、无二进制依赖，可作为不装 graphviz 时的回退引擎。

## 4. 工具链推荐与回退策略

- **渲染器 issue 05**：
  1. **首选 graphviz（dot）**：`rankdir=TB`、节点 `box`、`fontname` 指向 CJK 字体、
     `dpi=120`；对回流/环/多分支更稳。探测方式 `shutil.which("dot")`。
  2. **回退 matplotlib 分层渲染器**（仓库自带，接口一致）：无系统依赖，非全部装机
     可用；环时对回边做轻微弧度或接受少量重叠。
  3. 接口统一为 `render(diagram: Diagram, out_path: str) -> str`（返回输出路径），
     输入即 issue-02/05 的 canonical `Diagram` JSON。
- **抽取模型 issue 05**：
  1. **首选 `glm-5.3-flash`**：它是唯一能在真实大图 (`R01/R02`) 上抽出结构的模型，
     贴合目标「真实手稿照片」场景。
  2. **`deepseek-v4-flash-vision-exp` 作小图纠偏回退**：干净小图上结构更准
     （P=1.0），可作无图交叉校验；但大图必空内容，不能当主路径。
  3. **抽取失败 → `crop_diagram` 裁非背景 bbox 嵌入原图**，此路径不经文本/LLM，
     天然不会产生乱码（FR-009 降级语义）。

## 5. 降级（crop & embed）演示

`degrade_crop.crop_diagram()` 抠出非背景内容区域（阈值 <235 灰，含边距）存 PNG。
对所有 12 张样本生成 `plots/degrade/S0X_crop.png`、`R01_crop.png`、`R02_crop.png`，
产物为独立图片、无任何拼接文字，故无乱码风险；真实大图裁剪后 ~800KB（远小于原 ~2–3MB）。
空 content / R01 / R02 即为降级触发样本（见 §2）。

## 6. 交付物（本目录）

- `ir_model.py` / `extract.py` / `gateway.py` / `degrade_crop.py` / `compare.py`
  / `render_predictions.py` / `synthesize_samples.py` / `prepare_samples.py`
- `samples/`（12 张，宽 1280）、`ground_truth/S0X.json`（合成为精确真值）
- `cache/`（24 条记录）、`plots/{mpl,gv,pred,degrade}/`、`outputs/{compare_results,degrade}.json`
- `tests/`：15 个离线用例（解析/评分/确定性/graphviz 逐字节/crop 无乱码），全绿

## 7. 结论摘要（供 issue 05 消费）

1. **VLM 抽取可行**：干净流程图上两模型结构召回约 0.8–0.94、精确率 0.86–1.00，中文
   标签可正确读出；抽取成功率 ~83%。
2. **大图是主要风险**：`deepseek` 对 >~数百 KB 真实手稿**必空内容**；`glm` 可用但偶发
   空内容 → 必须「主模型 → 兜底模型 → crop&embed」三级策略。
3. **确定性重建可行**：graphviz 与 matplotlib 均逐字节可复现，满足 FR-020；推荐
   graphviz 主、matplotlib 回退。
4. **降级路径安全**：crop&embed 不经 LLM/文本，无乱码，实现成本低。
5. resource note：`max_tokens=10000` 下空内容仍偶发，建议抽取出增加「空内容重试另一
   模型」与失败统计。