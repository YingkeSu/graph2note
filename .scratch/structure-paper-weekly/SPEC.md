# SPW 共享契约（SPEC）

本文件是本轮两条轨道的**唯一契约来源**。各 worker 在并行开发时以本文件为准对齐数据形状；实现细节可超出本契约，但不得违反。

## §1 层次结构图 IR 扩展（D 轨）

### 问题陈述

现行 `DiagramBlock`/`FlowBlock` 只有扁平 `nodes[] + edges[]`：VLM 抽取（`diagram.py`）输出平铺节点，布局（`_layout.py`）只做最长路径分层，渲染无分组语义。对手稿中明显带**层次结构**的图（如 01-requirements-arch 的「层间通信 / 通信层 / 执行层」三层泳道、02-digitize-pipeline 的阶段管线 + 旁注），产物表现为：所有节点挤在少数层、泳道/分组丢失、旁注与主标签订混、边交叉多——即维护者所说「过于扁平、无层次、信息混乱」。

### IR 扩展（向后兼容，全部可选，缺省即现行行为）

在 `graph2note/ir.py` 的 diagram/flow 语义上扩展（pydantic 模型，extra 字段拒绝策略不变）：

```python
class DiagramGroup(BaseModel):
    """一个视觉分组（泳道/层/簇）。节点归属由 id 引用，不嵌套。"""
    id: str                      # 组内唯一
    label: str                   # 组标题，如「通信层」
    kind: Literal["layer", "lane", "cluster"] = "cluster"
    # layer=水平分层带（跨图整行）；lane=垂直泳道；cluster=局部簇
    nodes: list[str] = []        # 成员节点 id（须存在于 nodes[]）
```

- `Node` 增加可选字段：`note: Optional[str] = None`（次级说明文字，渲染为标签下方小字；用于手稿旁注如「坑：Tiger VNC 不支持」）。
- `Edge` 增加可选字段：`style: Literal["solid", "dashed"] = "solid"`（虚线用于旁注关联/弱关联）。
- `DiagramBlock` 与 `FlowBlock` 均增加：`groups: list[DiagramGroup] = []`。
- `document_type`、既有字段、校验严格性不变；无 `groups`/`note`/`style` 的旧 IR 与新模型双向兼容（旧 JSON 可加载，新 JSON 缺省字段序列化可省略或显式空值——由 D1 定夺并在 handoff 说明）。

### 语义与确定性要求

- **分组是视觉语义，不改变图的拓扑语义**：`groups` 不参与边合法性校验之外的任何逻辑；成员 id 必须存在于 `nodes[]`，悬空引用校验拒绝。
- **确定性**：`_canonical.py` 扩展为对 groups 同样规范化（按 id 排序、成员列表排序）；同一语义渲染字节一致（FR-020 延续）。
- **布局**：分组感知分层——同 layer/lane 成员优先同层/同列排布；层带按手稿自上而下的阅读顺序（layer 可携带 `order` 提示？——不允许，顺序由布局确定性推导，若 D2 认定必须保留 VLM 给出的层序，可在 `DiagramGroup` 增加 `order_hint: Optional[int]`，须在 handoff 记录该决策）。
- **渲染**：graphviz 用 `cluster_*` 子图；matplotlib 回退画分组背景框 + 组标题；group label 字号 ≥ 节点 note 字号；node.note 小一号字渲染。
- **抽取**：VLM 契约从扁平 nodes/edges 升级为「识别页面中的分层/泳道结构 → groups；主标签 vs 旁注 → label/note」。无层次可识别时合法输出空 groups（不强行编造层次）。

### 验收锚点（三张手稿图）

> 2026-09-14 更正（依 T-audit 阶段1 真实证据，报告 `/tmp/spw-T-audit-baseline.md`）：真实产物中「亮点：Critical Path 优化 ☆」出现在 **01** 的通信方案文字区（live IR node `n18`），不在 02；02 上真实存在的旁注区是「调研：」「设计：」。D 轨以本更正后锚点为准。

- 01-requirements-arch：应识别出 ≥2 个水平层带（层间通信/通信层/执行 区域），macmini/macbook/windows laptop 等节点归入对应层；右侧通信方案文字区（含「亮点：Critical Path 优化 ☆」、Questions、Programs 目录等）不得混入图节点（或作为 note/独立块）。
- 02-digitize-pipeline：阶段主线呈清晰主流向，旁注（「调研：」「设计：」等文字区）以 note/虚线弱关联呈现，不与主流程节点同级混排。
- 02-digitize-pipeline-increment：原图为左右两张独立流程（原子/增量）；产物应保持两侧可分辨（至少以 groups/子图区分），不得压成一张无区分的散点大图。
- 复验由 T-audit（几何/结构，判据见 `/tmp/spw-taudit-artifacts/MANIFEST.md` §9）+ T-vision（视觉判读）分执；视觉 verdict 以 T-vision 为准。

## §2 论文文档契约（I 轨 P1–P3）

### 问题陈述

现有 PDF 导入（`pdflib.py` + `pipeline.parse_document`）面向**手稿/扫描件**：每页渲染为图 → VLM 逐页解析。对**论文 PDF**（born-digital，带文本层）该路径浪费且失真：文本层被截图→VLM 重识别，标题/作者/参考文献等结构信息全部丢失。「论文导入模块」需要一条论文专用全线：文本层直提 → 结构识别 → 元数据/参考文献 → 入库 → 阅读视图。

### 数据形状

```python
class PaperMeta(BaseModel):           # P2 产出，P1 留槽位，P3 消费
    title: str = ""
    authors: list[str] = []
    year: Optional[int] = None
    venue: str = ""                   # 期刊/会议/arXiv
    doi: str = ""
    abstract: str = ""
    keywords: list[str] = []
    source: Literal["text-layer", "vlm", "manual", "none"] = "none"
    # 每个字段的识别来源与置信信息放入 provenance，不进 PaperMeta 本体

class PaperReference(BaseModel):      # P2 产出
    raw: str                          # 原始参考文献条目文本
    title: str = ""
    authors: list[str] = []
    year: Optional[int] = None
    doi: str = ""
    resolved_document_id: Optional[str] = None   # 库内已存在同 DOI/同标题论文时回填

class PaperSection(BaseModel):        # P1 产出
    level: int                        # 1=章 2=节 ...
    title: str
    text: str                         # 该节正文（含公式占位/图表占位）
    page_start: Optional[int] = None
    page_end: Optional[int] = None
```

- 入库文档带 `doc_kind: "paper"`（provenance/meta 字段，具体落点由 P1 定：`store.save_document` 追加式扩展，不改既有签名行为）。
- P1 产出：`sections: list[PaperSection]` + 全文纯文本 + 页映射；扫描版论文（无文本层）回退现有 VLM 逐页路径并在 provenance 标注 `source: "vlm"`。
- P2 产出：`PaperMeta` + `references: list[PaperReference]`，输入是「论文全文文本 + 首页文本 + 参考文献区文本」（P2 自建 fixture 开发，不依赖 P1 代码）。
- P3 消费：`doc_kind=="paper"` 文档的 meta/sections/references 只读展示；fixture 驱动开发。
- 全程确定性优先：文本层抽取与结构切分必须离线确定性可测；LLM 仅作为可选增强（提议 + schema 校验 + 人可改），无 key 环境全链路可用。
- 网络：默认不访问外部服务（CrossRef 等在线解析若做，必须可选、可关、测试离线）。

## §3 周报模块契约（I 轨 W1–W2）

- 现行：`digest.py` 单次 text LLM 调用生成一整篇 Markdown；dashboard.js 展示。
- W1 目标结构（生成结果 Markdown 的确定性骨架，LLM 逐节填充）：
  1. 本周概览（文档数/新增/解析成功率等确定性统计——不调 LLM）
  2. 主题脉络（按主题/标签聚合的要点）
  3. 重点文档摘录（每篇 ≤N 字，带来源链接）
  4. 待整理与连续体进展（inbox/continuity 统计 + 建议）
- 每节标注来源文档 id 列表（provenance），指纹缓存机制（现行 SHA-256）延续——材料不变零 LLM 调用。
- W2 只动展示/交互/导出，不改生成逻辑（与 W1 通过「digest meta.json 增加 sections 结构」契约解耦——W1 在 meta 中写入 `sections: [{key, title, source_document_ids}]`，W2 消费该字段，旧 meta 无此字段时回退现行整篇渲染）。
