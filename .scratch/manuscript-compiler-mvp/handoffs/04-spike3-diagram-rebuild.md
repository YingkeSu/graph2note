# Handoff 04 — Spike 3 结论 → issue 05（Diagram 渲染器）

> 来源：`issues/04-spike3-diagram-rebuild.md`（Status: in-review）。
> 全文测量与样本见 `spike3/report.md`、`spike3/outputs/`、`spike3/plots/`。
> 本文件只写结论与给 issue 05 的接口建议；**不改 IR schema**（归 issue 02 管）。

## 1. 一句话结论

端到端路径成立：`图 → VLM 结构化 → 确定性渲染`。VLM 抽取干净流程图成功率 ~83%、
结构召回 0.8–0.94；图形渲染两方案均满足 FR-020（同一语义逐字节一致）；失败时
`crop&embed` 降级安全无乱码。

## 2. 渲染器选型（issue 05 消费）

**优先 graphviz(dot)，matplotlib 手写分层布局为依赖无关回退。**

| 判据 | graphviz(dot) | matplotlib(手写分层) |
|---|---|---|
| 确定性 FR-020（两次渲染逐字节一致） | ✅ | ✅ |
| 节点重叠（10 图，含环/回流） | **0** | 3（环上回边引入少量重叠） |
| 连线交叉 | 0 | 0 |
| 中文标签 | ✅ 无豆腐块（fontconfig→Arial Unicode MS） | ✅ 无豆腐块 |
| 依赖 | 需 `dot` 二进制 | 纯 Python |

理由：graphviz 自动布局对回流/环/多分支更稳，零重叠零交叉，还省掉一份手写布局代码；
代价仅是 `dot` 系统依赖。因此 issue 05 建议：探测 `shutil.which("dot")`，可用则用
graphviz，否则回退 matplotlib。

## 3. 给 issue 05 的接口建议

- 两个渲染器统一签名：`render(diagram: Diagram, out_path: str) -> str`（返回输出路径）。
- 输入 `Diagram` 即 canonical JSON：
  `{"nodes":[{id,label}],"edges":[{src,tgt,label}]}`，渲染前先 `diagram.canonical()`
  （排序稳定，保证 FR-020）。
- graphviz 参数（已验证）：`rankdir=TB`、节点 `shape=box`、`fontname` 指定 CJK 字体
  （如 `Arial Unicode MS`，可用 `fc-match` 探测）、`dpi=120`。
- matplotlib 参数（已验证）：`rcParams["font.sans-serif"]` 设 CJK 字体；分层 = 最长路径
  + 迭代松弛（环安全）+ 重心序；回边可轻微圆弧化以减重叠。
- 中文标签两方案都直接吃 `label` 字符串，渲染层不转码 → 天然无乱码；乱码只会来自
  发往 VLM 前的字符集错误，见 §4。

## 4. 抽取模型选型（issue 05 / spike 1 联合消费）

- **主用 `glm-5.3-flash`**：12 样本里唯一能在真实大图（R01/R02，~800KB）上抽出结构
  的模型（R01 完整 5 节点 6 边含回边、中文多词标签）；成功率 10/12。
- **`deepseek-v4-flash-vision-exp` 作小图纠偏回退**：干净小图上结构更准（S01–S09
  精确率全 1.0，召回 0.94），但两张真实大图**一律空 content**，不能作主路径。
- 三级策略：主模型 →（空 content/parse_fail 时）兜底模型 →（仍失败）crop&embed。
  空 content 触发率实测 ≈ 17%（4/24 = 大图×2 模型 + 两个合成空响应）。

## 5. 降级（crop&embed）契约

`degrade_crop.crop_diagram(src, out_path, max_width=900)`：取 <235 灰的非背景 bbox，
+边距裁剪存 PNG（超宽按比例缩小，控制仓库体积 516KB 级）。该路径不经过任何文本/OCR
/LLM，因此不可能产生乱码。issue 05 在抽取失败时调用它，把裁剪图作为 Diagram 块的原图
兜底嵌入。

## 6. 建议在 issue 05 里落实

1. 渲染器选 graphviz 优先、matplotlib 回退（同一 `render()` 契约）。
2. 给每个 Diagram 块记录 `{engine, rendered_path}` 与失败时 `{degraded, crop_path}`，
   便于审计与再渲染。
3. 持续统计：每图抽取成功率、空 content 率、降级触发率（issue 验收沿用）。
4. 真实手稿 HITL 图集接入后重新跑一遍成功率（用 issue 01 评估集样本）。

## 7. 相关文件

- 报告：`spike3/report.md`
- 实现：`spike3/{ir_model,extract,gateway,degrade_crop,compare,plot_matplotlib,plot_graphviz,plot_graphviz_geometry,render_predictions,synthesize_samples,prepare_samples}.py`
- 样本/数据：`spike3/{samples,ground_truth,cache,plots,outputs}/`
- 测试：`spike3/tests/`（15 项全绿，无网络）
- PRD 开放问题回写：`PRD.md`（绘图工具链选型已决策）