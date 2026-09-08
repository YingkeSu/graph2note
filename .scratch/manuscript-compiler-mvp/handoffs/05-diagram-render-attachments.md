# Handoff 05 — Diagram 渲染+附件（产品化）

> 来源：`issues/05-diagram-render-attachments.md`（Status: in-review）。
> 消费者：issue 03（解析层产出带 nodes/edges 或 `source` 的 diagram/flow block）、
> issue 06（Web UI 导出与附件打包）、后续维护者。
> Spike 证据：`spike3/`（本 issue 只在其上产品化，不做双份维护）。

## 1. 交付内容

`graph2note/diagrams/`（新产品代码）打通
`diagram/flow block(nodes/edges) → 确定性 PNG 资产 → assets/<doc>-<kind>-<index>.png → Markdown 相对路径嵌入`：

- `engine.py`：引擎选择策略 + `render_to_png(nodes, edges, source, out_path)` 统一入口。
- `graphviz_renderer.py`：首选引擎（dot），`rankdir=TB`、CJK fontname。缺 python 包或
  `dot` 二进制时 `available()` 为 False -> 干净回退（模块顶 import 有 try/except，导入永不抛）。
- `matplotlib_renderer.py`：纯 Python 回退引擎，手写分层布局（`_layout.py`，环安全）。
- `_canonical.py`：渲染前按内容规范化 nodes/edges 顺序，保证仅依赖图内容而非输入顺序（FR-020）。
- `degrade.py`：`crop_image`（非背景 bbox 裁剪，无 OCR/文本管线 -> 不可能乱码）+ `blank_png`（无结构无源图时的确定性空白占位）。
- `attachments.py`：`FileAssetWriter` 改为真实绘制；保留 `PlaceholderAttachmentWriter`（默认纯函数路径）。
- `attachments.missing_attachments(md, assets_dir)`：附件完整性检查，缺失引用明确列出。

新测试：`tests/test_diagrams.py`（14 项），`tests/` 合计 **54 全绿、无网络**。
示例：`examples/diagram-demo.ir.json`（结构化 diagram + flow + 降级 crop 三段），
`python -m graph2note.cli examples/diagram-demo.ir.json -o out.md --assets-dir .`。

## 2. 引擎选择决策（沿用 issue 04 结论）

- **首选 graphviz/dot**：零节点重叠、零交叉对回流/环更稳，省手写布局。
- **回退 matplotlib**（`prefer="matplotlib"` 或 graphviz 不可用）：纯 Python，无系统依赖。
- 两引擎均满足 FR-020（同一语义两次渲染逐字节一致，有回归测试）。
- `prefer` 参数：默认 `"graphviz"`（可用才用），可强制 `"matplotlib"`。

## 3. IR 向后兼容扩展（关键决策）

在 `ir.py` 的 `_DiagramMixin`（diagram/flow 共享）新增**可选**字段：

```python
source: Optional[str] = None   # 原手稿图引用，仅降级路径使用
```

- **向后兼容**：默认 `None`；旧文档（无 `source`）照常校验/渲染；新文档可带 `source`。
- **未加 bbox 字段**：裁剪时自动探测非背景 bbox，故无需显式传框；若未来需要显式框，
  再加 `bbox: Optional[list[int]]`（同样默认 None）。此处保持最小扩展。
- `render.py` 把 `block.source` 透传进 `DiagramSemantics`；`FileAssetWriter` 在无结构且有
  source 时走 `crop_image`，无结构无 source 时写 `blank_png` 占位（附件引用仍可解析）。

## 4. 降级（crop&embed）路径

- 触发：block 无 nodes 且无 edges（VLM 未给出结构语义）。
- 行为：`source` 存在 -> 裁非背景 bbox 存 PNG 嵌入；`source` 缺失 -> 确定性空白占位（不抛、
  不中断导出）。`source` 指向不存在文件 -> 抛 `FileNotFoundError`（显式、可诊断）。
- 无乱码保证：该路径不经过任何 OCR/文本/LLM。

## 5. 附件完整性

- `missing_attachments(markdown, assets_dir)`：正则提取 `](...)`，只检查 `assets/...` 相对
  引用，忽略 http(s)/绝对路径/data URI；缺失则列入返回列表。AC「每个图片引用都有对应文件」。

## 6. 待办/边界（留给后续）

- issue 03 解析层：抽取失败时产出**带 `source` 且空 nodes/edges** 的 diagram block，
  即可无缝接入降级路径；抽取出结构化语义则产出 nodes/edges（走确定性重建）。
- issue 06：导出 `.md`+assets 打包时用 `missing_attachments` 做完整性门禁；`index` 为
  block 序号（与 issue 02 契约一致，非逐图计数）。
- 后续若需逐图审计：`FileAssetWriter.results` 已记录 `(rel_path, {engine, degraded, notes})`。

## 7. 依赖

- 运行：`pydantic`；结构化重建可选 `graphviz`（python 包）+ 系统 `dot`，fallback 需
  `matplotlib`；降级需 `pillow`+`numpy`。全部未触网。
- 测试：`pytest`；graphviz 用例在包/二进制缺失时干净 SKIP（`importorskip` + `available()` 双检）。
