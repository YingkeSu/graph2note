# Handoff — issue 02: Document IR schema + deterministic Markdown renderer

Branch: `dev/02-ir-schema-renderer`
Worktree: `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-2`

## 完成了什么

本 issue（Track A）交付一个纯 Python 库 + CLI，实现系统中心数据契约与确定性 Markdown 渲染器，不含 LLM、不触网。

- **IR schema**（`graph2note/ir.py`，pydantic v2，机器可校验）：
  - `DocumentIR`：`document_type` + `blocks` + 向后兼容 `version` 标记。
  - 10 种 block 类型全集：`heading / paragraph / list / formula / table / code / quote / image / diagram / flow`。
  - `diagram` 与 `flow` 都以**结构化语义** `nodes/edges` 表达（`Node{id,label}`、`Edge{from,to,label}`；JSON 键为 `from`，内部字段 `from_` 用 pydantic alias）。`flow` 额外带 `orientation`。
  - `list` 支持嵌套（`ListItem{text, items}` 递归）。
  - 校验严格：未知类型、缺字段、类型错误、越界、非法 JSON、根非对象、额外未知键都会抛 `IRValidationError`（可读信息含字段路径）。`loads_ir` / `dumps_ir` 为进出入口。
- **确定性 Markdown 渲染器**（`graph2note/render.py`）：`render_markdown(doc, doc_id, attachment_writer)` 为纯函数，同一 IR 两次渲染逐字节一致（有回归测试）。规则：heading→ATX；list→`-`/`1.` 列表并缩进嵌套；formula→行内 `$…$` / 独立 `$$…$$`；table→管道表（单元格转义 `\|`）；code→围栏块（围栏长度自动超过内容内反引号最长游程）；quote→`>`；image→`![alt](src)`。正文特殊字符 `\ ` ` * _ { } [ ] < > #` 反斜杠转义防结构注入；中文全角与标点原样保留（只转义 ASCII 标点）。
- **附件接口**（`graph2note/attachments.py`）：本 issue 只留 seam。`AttachmentWriter` ABC，`diagram/flow` block 渲染为 `![caption](assets/<doc>-<kind>-<index>.png)` 相对路径，语义对象交给 writer。提供 `PlaceholderAttachmentWriter`（纯函数路径，不落盘）与 `FileAssetWriter`（可选落盘 stub PNG，供 issue 05/06 验证 `.md`+资产打包）。**绘图实现在 issue 05，本处绝不实现。**
- **CLI 演示入口**（`graph2note/cli.py` + `examples/note.ir.json`）：
  `python -m graph2note.cli examples/note.ir.json -o out.md [--assets-dir assets] [--stdout]`
  IR JSON 进、`.md` 出；非法 IR 返回码 1 并打印原因。
- **测试**：`tests/` 共 **31 个用例** 全绿（`pytest -q`），覆盖：IR 校验（合法 10 类型 / 7 类非法样本）、渲染确定性（含 JSON round-trip）、10 类型 golden 全量、嵌套列表（深层）、特殊字符转义、中文全角保留、行内/独立公式、表格管道转义、代码围栏反引号、diagram/flow 附件路径、FileAssetWriter stub 落盘、CLI 出入文件/bad IR/缺文件。无网络、无 mock。

## 如何运行测试

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-2
python3 -m pytest -q        # 31 passed
```

库依赖：`pydantic>=2.0`（已装 pydantic 2.13.2）。`pyproject.toml` 已配置，`pip install -e .` 可选（CLI 亦可用 `python -m graph2note.cli` 直接跑，无需安装）。

## 决策与对 spec 的偏离

- **决策**：选 **pydantic v2** 而非 JSON Schema——类型安全、递归模型（list/diagram）自然、校验错误同学段可直接读。
- **决策**：转义字符集取 `\ ` ` * _ { } [ ] < > #`（CommonMark 可转义的 ASCII 标点 + 防 HTML 注入的 `<>`）。中文全角字符（含全角 `，。（）＊`）不在集合内，原样保留，满足「全角不半角化」。
- **决策**：table 单元格单独走 `_escape_cell`（先 `|→\|`，再转义其它特殊字符），避免经通用 `escape_text` 双重转义成 `\\|`。
- **决策**：diagram/flow 的附件相对路径以 `doc_id`（默认 `doc`，CLI 用 IR 文件名 stem）+ block 序号派生，是纯函数，保证确定性且不依赖绘制。
- **偏离/预留**：为 P1（HTML/PDF、模板）预留 `version` 字段与「内容≠表现」的纯语义 block 设计，但**未做**插件/模板注册机制（避免过度设计，此处仅预留扩展点）。

## 未尽事项 / 给接力者建议

- **issue 05（Diagram 渲染+附件）**是直接下游：实现 `AttachmentWriter` 的真实绘图（`DiagramSemantics.nodes/edges` → matplotlib/graphviz → 落盘 assets），替换 `PlaceholderAttachmentWriter`。本 issue 的 `![...](assets/...)` 路径与 `FileAssetWriter` 的 `.md`+assets 布局是它的稳定输入契约。
- issue 05/06 做**附件完整性检查**时可沿用：Markdown 内每个 `](...)` 引用在 assets 目录有对应文件。
- `formula`/`table` 契约已入 IR（PRD 要求第一天进），但识别质量属 P1，**非本 issue 验收项**。
- 若后续 renderer 需要 `image` block 相对/绝对路径规范化，属增强，未在本 issue 实现。
- 未触碰解析层/LLM（issue 03）、绘图实现（05）、Web UI（06）——按边界不做。

### Suggested skills
- `diagnose`：如需排查渲染确定性 / 转义边界回归。
-（本 issue 为纯 Python + pytest，无 UI，`impeccable`/`prototype` 不适用。）