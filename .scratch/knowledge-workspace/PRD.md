# PRD：Knowledge Workspace — Web 知识工作台（时间组织 / 图谱 / 统计）

Status: ready-for-agent
Version: v0.1
Created: 2026-09-10
Phase: P2（依赖 manuscript-compiler-mvp 文档库与 notes-organizer 分类能力）
Parent feature: manuscript-compiler-mvp（消费其 DocumentRecord）；复用 notes-organizer 的 ClassificationScheme

> 一句话：**在已交付的「解析 → Markdown → 文档库 → Obsidian 导出」之上，把 Web 端从平铺文档列表升级为知识工作台：时间轴、关系图谱、Dashboard 统计、集合与标签管理——回答「这份内容属于哪里、什么时候产生、和什么相关、花了多少成本」。**

## Problem Statement

Manuscript Compiler 与 notes-organizer 交付后，纸质手稿已能稳定变成结构化 Markdown 并导出 Obsidian vault，但知识管理体验止步于导出那一刻：

- **Web 端只有一个平铺列表**：文档多了之后，同一主题散落各处、看不到任何组织维度；分类成果（ClassificationScheme、MOC）只活在导出的 vault 里，Web 内不可见、不可管理。
- **时间脉络丢失**：系统只记录导入/修改时间；手稿的真实创作时间（EXIF 拍摄时间、手写的页眉日期）没有进入数据模型，无法按「什么时候写的」回看项目推进。
- **标签体系缺治理**：自动打标没有「已有标签优先」约束，随着语料增长必然标签爆炸（#AI / #人工智能 / #ArtificialIntelligence 三胞胎）。
- **成本与用量不可见**：解析遥测（模型、token、延迟）散落在每次运行的 timing 产物里，没有随文档持久化，也没有聚合视图——用户不知道这套系统一个月花多少、哪个模型划算。

用户要的不只是「文档被正确解析」，而是**知识库**：能按时间回溯、按关系导航、按统计洞察的活的工作空间。

## Solution

在 DocumentRecord 与 ClassificationScheme 之上增加**工作台层**（独立于解析管线，只读消费 + 元数据写回）：

```
DocumentRecord ─┬─ 时间模型（capture / document / import / modified 四时间戳）
                ├─ 集合与标签（collection CRUD、标签词表与规范化治理）
                └─ 解析遥测持久化（token / 延迟 / 模型随版本落库）
                        ↓
            Workspace 视图模型（纯函数）
                        ↓
   Timeline（按文档时间组织） · Graph（文档-主题-标签关系） ·
   Dashboard（今日/本周/历史、分类分布、标签使用、token 成本） · Inbox（待整理）
                        ↓
              Web UI（视图需求与 API 契约先行，前端技术不锁）
```

- **时间模型升级**：四时间戳区分「拍摄时间（EXIF）→ 手稿日期（内容推断）→ 导入时间 → 修改时间」；时间轴按 `手工修正 > 手稿日期 > 拍摄时间 > 导入时间` 的优先级排序。
- **标签治理**：持久化标签词表，自动打标「能复用不新增」，提供合并/重命名/使用统计；与主题分类（ClassificationScheme，粗粒度）分层共存——topic 管归档结构，tag 管检索维度。
- **集合（collection）**：文档可属多个集合（非物理互斥目录）；默认集合由分类方案推导，用户可新建/移动/重命名/删除。
- **Graph**：文档 ↔ 主题 ↔ 标签关系图，边携带来源标记（`topic / tag / manual`，预留 `inferred`）；本期不新增任何「AI 推断关系」的模型调用，图谱完全由已有数据派生。
- **Dashboard 与 Token 统计**：聚合随版本持久化的解析遥测，给出今日/本周/累计页数、分类分布、标签 Top、按模型 token 用量与成本估计。
- 平台定位不变：个人自用、本地部署、数据不出本机。

## User Stories

### 时间模型

1. 作为用户，我想每份文档自动区分拍摄时间、手稿日期、导入时间、修改时间，以便时间轴反映真实创作顺序而不是导入顺序。
2. 作为用户，我想系统从图片 EXIF 读取拍摄时间作为 capture_time，以便手机拍照的时间不丢失。
3. 作为用户，我想系统从手稿内容（页眉日期、标题中的日期线索）推断手稿日期，以便手写的日期进入时间轴。
4. 作为用户，我想日期推断带有置信度与依据展示，推断错误时可手工修正且修正优先级最高，以便时间轴可信、可纠偏。
5. 作为用户，我想在时间轴里按天/周切换分组粒度，以便既能看某一天的细节也能看一个月的节奏。

### 标签治理

6. 作为用户，我想自动打标签优先复用已有标签，以便不出现同义标签三胞胎。
7. 作为用户，我想新增标签经过规范化（空白/大小写/分隔符统一），以便词表天然干净。
8. 作为用户，我想看到全部标签与使用次数，并支持合并与重命名，以便长期治理标签体系。
9. 作为用户，我想手工给文档补打/移除标签，以便纠正自动结果。

### 集合与工作台

10. 作为用户，我想在 Web 里用集合组织文档（新建、移动、重命名、删除），以便不再面对平铺列表。
11. 作为用户，我想一个文档可以同时属于多个集合，以便「毕业设计」和「强化学习」两个视角都能收录同一份笔记。
12. 作为用户，我想集合与 Obsidian 导出的分类文件夹有明确映射规则，以便两边不打架。
13. 作为用户，我想工作台侧栏默认显示今日/本周新增与最近编辑，以便快速回到正在进行的工作。

### Timeline

14. 作为用户，我想按时间轴浏览全部文档（按手稿日期优先排序），以便看到项目和课程的推进脉络。
15. 作为用户，我想时间轴里同一主题的相邻笔记聚合展示，以便看到「这个方向我是怎么一步步想清楚的」。
16. 作为用户，我想从时间轴条目直接打开三栏编辑器，以便回溯时可以继续修正内容。

### Graph

17. 作为用户，我想在 Web 里看到文档-主题-标签关系图，以便不开 Obsidian 也能总览知识结构。
18. 作为用户，我想图中不同来源的边（主题归属/标签/手工）视觉可区分，以便不把派生关系误当强关系。
19. 作为用户，我想点击图节点跳转到对应文档列表或标签过滤，以便图谱是导航入口而不是挂画。

### Dashboard 与统计

20. 作为用户，我想看今日/本周/累计的解析页数与新增文档趋势，以便了解自己的使用节奏。
21. 作为用户，我想看分类分布与标签使用 Top，以便发现失衡的分类和冗余标签。
22. 作为用户，我想看每批解析的 token 用量（输入/输出/推理）与成本估计（按模型、按日/月汇总），以便知道这套系统花了多少钱。
23. 作为用户，我想看平均耗时与重试率统计，以便判断模型与管线配置是否要调。

### Inbox 与数据一致

24. 作为用户，我想有 Inbox 收纳未分类、无标签或被标记待整理的文档，以便定期集中清理而不是随手积压。
25. 作为用户，我想在工作台做的标签/时间/集合修改能持久化，并在下次 Obsidian 导出时生效，以便 vault 与工作台始终一致。
26. 作为用户，我想工作台所有视图只读消费解析产物，内容编辑仍走三栏界面，以便两套交互各司其职、架构不乱。

## Implementation Decisions

- **分层独立**：工作台层只读消费 DocumentRecord（IR + Markdown + 附件）与 ClassificationScheme，不回写解析管线；元数据（时间/标签/集合归属）作为**文档级元数据**写回 store，与内容版本解耦——延续 notes-organizer「整理层独立」与 Content ≠ Presentation 原则。
- **时间模型**：DocumentRecord 元数据新增四时间戳。capture_time 在预处理阶段顺手提取（该阶段已读 EXIF 做方向转正，同一 seam）；document_time 由轻量文本 LLM 从 Markdown 内容推断（复用 IR stage-2 的文本模型通道与网关会话策略），输出「日期 + 置信度 + 依据片段」并过 schema 校验；用户手工修正值优先级最高且不自动覆盖。
- **标签词表**：持久化标签词表（含规范化形式与别名）；自动打标复用 notes 分类 LLM seam，prompt 携带已有词表并要求「能复用不新增」；主题（topic，粗粒度归档）与标签（tag，细粒度检索）分层，互不替代。合并/重命名是词表操作，批量更新文档归属。
- **集合语义**：collection 是多对多归属，不搬动物理文件；默认集合由 ClassificationScheme 的 topic 推导；Obsidian 导出时按「集合 → 文件夹」映射落位（导出器已有分类逻辑上扩展，幂等与不覆盖用户修改的决策沿用）。
- **解析遥测持久化**：每次解析的遥测（模型、prompt/completion/reasoning tokens、延迟、重试、缓存命中）随版本记录落库（当前只在运行期 timing 产物中，attempts 字段已预留 token 位但网关未回填 usage——本期补全网关 usage 捕获）；成本估计用本地价目配置，不引入外部计量服务。
- **视图模型为纯函数**：`DocumentRecord[] + ClassificationScheme + 元数据 → timeline / graph / dashboard / inbox 视图数据`，确定性、可快照；Graph 边来源枚举 `topic | tag | manual`，本期不产生 `inferred` 边、不新增模型调用。
- **API 契约（前端技术不锁，契约先行）**：现有 `/api/documents` 系列不变；新增只读为主的工作台端点——统计聚合（`/api/stats`）、时间轴（`/api/timeline`）、图谱（`/api/graph`）、集合 CRUD（`/api/collections` + 文档归属变更）、标签词表（`/api/tags`，含合并/重命名）、文档元数据读写（`/api/documents/{id}/metadata`）。具体形态以 SPEC 为准。
- **前端视图需求**（供并行进行的界面设计）：工作台布局为「左侧集合/导航树 + 中间内容区 + 右侧今日/本周/历史侧栏」；核心视图为 Library（现有列表升级）、Timeline、Graph、Dashboard、Inbox 与既有三栏编辑器；技术栈（演进现有静态 app 或框架重写）由实现期决定，API 契约与交互行为是唯一约束。
- **回填与增量**：时间推断、标签、集合归属对存量文档可批量补跑（复用 notes 增量导出的「以 document_id 为锚」模式），不要求一次性迁移。

## Testing Decisions

沿用仓库三个既有 seam 风格（只测外部行为、不 mock 到实现细节、CI 无 live 调用），经维护者确认按三层设置：

1. **视图模型 seam（最高价值）**：`Record[] + Scheme + 元数据 → 各视图数据` 为纯函数，fixture 进、期望快照出——覆盖时间排序优先级链（手工 > 手稿日期 > 拍摄 > 导入）、时间轴分组、图谱节点边与来源标记、Dashboard 聚合口径、Inbox 判定规则。不触网、确定性可回归。
2. **元数据推断 seam**：EXIF 拍摄时间用合成图片（已知 EXIF）确定性测试；手稿日期推断与自动打标的 LLM 输出录制 golden fixtures，推断结果过 schema 校验（日期合法性、置信度分档、标签必须来自词表或走新增规范化）后才能落库。
3. **API 集成 seam**：新增端点以 stub store / 录制数据驱动（TestClient，无 LLM），验证契约行为（集合 CRUD、标签合并的批量效果、元数据读写、统计口径），沿用 webapp 现有测试先例。

好测试的标准：视图模型测试不感知 prompt 与存储路径；推断测试只校验「LLM 输出 → 落库数据」的契约行为；聚合统计用固定 fixture 保证口径可复现。

## Out of Scope

- **版本间语义对比（Semantic Diff）与连续手稿演进关联**（v1→v2 自动识别为同一项目的演进）——与本期紧耦合但独立成篇，另立 PRD（维护者已确认）。
- 增量 Semantic Merge（新版手稿只并入变化区域）——Advanced，不排期。
- 块级混合路由（同页 OCR / VLM / 公式分道）——Spike 2 证据不支持急做，维持 P2 观察。
- 统计图/图表重绘（Chart Parser）——维持 P2。
- Mermaid renderer——当前 graphviz/matplotlib PNG 重建达标；若 vault 内需要原生 mermaid，另开小 issue，不占本期。
- Obsidian 双向同步 / 插件开发——维持 notes-organizer 决策（单向导出、不覆盖用户修改）。
- 新增「AI 推断文档关系」的模型调用——图谱边只来自已有数据（topic/tag/手工），`inferred` 边为将来预留。
- 多用户、云同步、移动 App——平台定位不变。

## Further Notes

- **与 2026-09-10 手稿 PRD 草案（GPT 识别稿）的对照**：草案中的 Recognition Router、Document IR、结构化 Markdown、流程图重建、自动分类 + Obsidian 集成（溯源/MOC/增量导出）均已在 manuscript-compiler-mvp 与 notes-organizer 交付，本 PRD 只承接其「知识工作台」增量（时间轴/图谱/Dashboard/Token 统计/文件夹管理/标签治理）；草案中「增量处理」一处字迹不确定，按 Semantic Merge 归入 Out of Scope；「交叉比对」按版本间 Semantic Diff 归入后续独立 PRD。
- 前端界面由维护者并行设计；API 契约与视图需求是设计稿与实现的协作界面，SPEC 阶段冻结字段形态。
- 开放问题（不阻塞 PRD，SPEC/实现期决策）：时间轴分组粒度的自适应规则（日/周切换是否自动）；成本价目表的维护方式与默认币种；标签词表的初始种子（是否从已有 ClassificationScheme 的 topic 别名冷启动）；Inbox「待整理」的判定阈值（无标签即入，还是含低置信交叉验证标记）。
- 依赖：manuscript-compiler-mvp issue 07（DocumentRecord 持久化）、issue 10（交叉验证标记，Inbox 低置信信号的候选来源）、issue 11（timing 遥测）；notes-organizer 全部（ClassificationScheme、导出幂等锚点）。
