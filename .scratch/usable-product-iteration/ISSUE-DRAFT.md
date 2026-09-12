# 拆分草案：usable-product-iteration

日期：2026-09-12
Status: draft-for-maintainer（维护者已确认方向：UX 优化 / 存量数据修复 / Semantic Diff / PDF 问答增强，同日追加：自动整理标签 / 每周小结 / 自定义 LLM API；本文将方向落成可派发 issue）
上游输入：维护者口述（"当前用户体验很差，思考如何优化"、"推荐一次将所有 issue 放在一起，有自动分配队列"）、`../baseline-and-next-iteration/BASELINE.md` 欠账清单、knowledge-workspace PRD 的 Out of Scope 预留（Semantic Diff 另立 PRD）、2026-09-12 对真实文档库（43 篇）的 UI 实地考察。

## 0. 一句话

**把已经建成的系统变成好用的产品**：先还清存量坏数据，再把信息架构和交互拉到概念稿水准，然后叠加两项已预留的新能力（版本间 Semantic Diff、PDF 多轮/跨文档问答）。

## 1. UX 实地考察结论（2026-09-12，真实库 43 篇，1440×1000 截图）

用仓库自带 `graph2note visual-qa capture` 对 Library / 编辑器 / 时间轴 / 图谱 / 看板逐页截图考察。痛点按严重度排序：

### P0 — 信息架构（最大的问题）

1. **顶栏 8 个平铺按钮**（文档库/Inbox/时间轴/知识图谱/数据看板/LLM 设置/导出 Vault/新解析）无分组无当前态，每轮迭代加一个按钮，已经挤成一排小字按钮。
2. **Library 首页纵向堆 6 个区块**：PDF 搜索+问答表单、集合树、快捷入口、标签词表、文档网格、空状态——全部平铺后首屏只能看到 1–2 个文档卡片。概念稿（`../knowledge-workspace/design/01-note_compiler_concept.html`）设计的是左侧栏布局，实现退化成了堆叠。
3. **PDF 搜索与问答埋在 Library 页内部**，不是一级入口；问完一次刷新就没了。

### P1 — 核心视图质量

4. **文档卡片信息密度过低**：只有文件名（全是 `手稿_20260912_143002.jpg` 风格，无法区分）+ 5 行预览文本（多为空或同一句话），**无缩略图、无日期、无标签**。43 篇文档视觉上不可辨识。
5. **编辑器纵向过载**：三栏（原图 430px/编辑器/预览）下方纵向堆叠状态栏、标签表单、集合表单、时间元数据面板、操作按钮——元数据在折叠线以下；三栏被压缩，手稿原图 430px 宽看不清细节，无放大。
6. **图谱不可用**：43 个文档节点全量渲染互相重叠，无缩放、无平移、无过滤；边混在一起分不清 topic/tag 来源。
7. **时间轴是"分组卡片列表"**而非时间轴：无刻度、无密度感、条目无缩略图。

### P2 — 通用

8. 无全局搜索（非 PDF 文档的内容搜不到）、无快捷键、无批量操作。
9. 全屏 spinner 阻断式等待，解析期间什么都不能做。

### 根因判断

功能是按 issue 纵向叠加的（每轮往 `index.html` 塞一个 section），从未做过横向的布局/导航整合。**UX 问题的 80% 是信息架构问题，不是美化问题**——所以本轮 UX track 以 U1 布局重构为地基，其余视图 issue 在新骨架上并行。

## 2. PRD 级决策（维护者已授权规划；如需推翻在派发前改本文）

### 2.1 UX track

- **布局对齐概念稿**：左侧栏（视图导航 + 集合树）+ 精简顶栏（品牌 + 全局搜索 + 新解析 + 设置），内容区按视图切换。概念稿仅供参考不构成契约（沿 knowledge-workspace PRD 口径），但布局骨架以此为目标。
- **技术栈不动**：继续 vanilla JS + `zero-build` 哲学（CDN 引 marked/KaTeX），把 1652 行 `app.js` 拆成 ES modules；**不引入前端框架、不加构建步骤**。理由：个人本地工具、当前痛点是 IA 不是维护性，框架重写成本不成比例。
- **验收手段**：每个 UX issue 用既有 `graph2note visual-qa capture` 截图前后对比 + 离线 DOM 断言测试；不新增依赖。
- **范围**：桌面 ≥1280px 为主场景；窄屏 best-effort 不做承诺。

### 2.2 存量修复 track（R）

- 修复对象：2026-09-12 实测用户库 43 篇中 **22 篇 `preprocessed.png` 仍为纯黑**（黑图透视 bug `c6f8c52` 修复前解析的存量；名单与机理见 `../baseline-and-next-iteration/handoffs/fix-black-preprocess.md`）。
- 路径：从完好的 `preprocessed_raw.png` 用修复后管线重跑，不要求重新上传。
- **预算纪律**：重跑 = 每页一次真实 VLM 调用，必须先 dry-run 报告（页数、预估调用数），CLI `--yes` / Web 用户点击确认后才执行；沿用 LLM 配额纪律。

### 2.3 Semantic Diff track（S）

knowledge-workspace PRD 已确认"另立 PRD"，本文代行其决策：

- **锚定模型**：主锚 = 同 `document_id` 的版本链（version N-1 vs N；`store.py` 已支持 `versions_for_document`，`ir.json` 每版本完整落盘——diff 不需要重新解析）。辅锚 = `versions_for_original_phash` 跨文档同页候选（issue 13 交付），仅作"可能是演进"的**建议**，由用户确认，不自动关联。
- **diff 层**：Document IR 块级（非文本 diff）：块的新增/删除/修改/移动 + 块类型（标题/段落/公式/图表）；输出结构化 DiffReport（纯函数、可快照测试）。
- **UI**：编辑器内版本切换 + 并排对照（Markdown 渲染级 + 原图对照）+ "此版本改了什么"摘要。
- **不做**：自动合并（Semantic Merge 维持 Out of Scope）、跨文档自动关联。

### 2.4 PDF 问答增强 track（P）

baseline 迭代留白项，本文代行决策：

- **多轮**：会话态（内存 + 可选落盘），上下文携带最近 5 轮；每轮答案的页级引用独立可点。
- **跨文档**：scope 从单 PDF 扩展到多 PDF/全部已导入；检索仍用现有关键词索引（pdfsearch），**首版不做向量检索**（与"PDF 先做关键词检索"既定决策一致；embedding 通道留作开放问题）。
- **统一搜索**：文档 Markdown 内容进检索索引，与 PDF 内容共用一套搜索入口（⌘K / 顶栏搜索框），命中可跳转文档编辑器或 PDF 原页。
- **不做**：长期对话历史管理、对话式 UI 之外的记忆能力。

### 2.5 智能助理 track（A，维护者 2026-09-12 追加）

- **A1 自动打标签**：现状 = 词表治理与 `store.add_auto_tags`/`validate_tag_inference` 校验骨架已交付（knowledge-workspace issue 02），但**无 LLM 推断函数、未接管线**。本 issue 补全：推断（词表优先）→ 单图/PDF 页/R1 重跑三入口自动挂标（失败不阻塞解析）→ 编辑器复核（auto/manual 可区分）→ 存量 `tags backfill`（预算纪律沿 R1）。
- **A2 每周小结**：按需生成而非定时任务；范围 = 有效时间优先级链；素材组装确定性 + 指纹缓存（同指纹零增量 LLM 调用）；单次文本通道调用（purpose session 隔离）；落盘 `digests/` 含来源与遥测；入口 = 看板区块 + API（CLI 可选）。**不做**：定时自动生成、推送/提醒。
- **A3 自定义 LLM API**：对齐 GitHub 主流 agent 项目（OpenCode/Cherry Studio/LobeChat 等）的自定义供应商通用形态——名称 + Base URL + API Key + 模型列表，OpenAI Chat Completions 兼容、模型名透传；按用途指派沿用现有 channels；**Key 只写不读**（存储于 storage 内 `llm-settings.json`，与 `.env` 同级本机安全假设，文档明示）。

## 3. Issue 拆分与依赖图

| Issue | Track | 一句话 | Blocked by |
|---|---|---|---|
| [R1](issues/R1-black-image-repair-loop.md) | 修复 | 黑图检测 → 确认 → 从 raw 重跑 → 验收 22 篇 | 无 |
| [U1](issues/U1-global-layout-navigation.md) | UX | 侧边栏+精简顶栏+路由修复（地基） | 无 |
| [U2](issues/U2-library-cards-grid.md) | UX | 文档卡片富化（缩略图/日期/标签）+ 网格重排 | U1 |
| [U3](issues/U3-editor-workspace.md) | UX | 编辑器信息侧板化 + 原图放大查看器 + 快捷键 | U1 |
| [U4](issues/U4-graph-interaction.md) | UX | 图谱缩放/平移/过滤/聚焦邻域 | U1 |
| [U5](issues/U5-timeline-visual.md) | UX | 时间轴可视化形态 + 条目缩略图 | U1 |
| [P1](issues/P1-pdf-multiturn-qa.md) | PDF | 多轮问答（会话态+上下文） | 无 |
| [P2](issues/P2-qa-conversation-ui.md) | PDF | 对话式问答 UI + 一级入口 | U1, P1 |
| [P3](issues/P3-cross-doc-unified-search.md) | PDF | 跨文档问答 + 文档内容入统一索引 + ⌘K | P1（U1 建议先行） |
| [S1](issues/S1-ir-block-diff.md) | Semantic | IR 块级 diff 引擎（纯函数 + DiffReport） | 无 |
| [S2](issues/S2-evolution-anchoring.md) | Semantic | 版本链锚定 + pHash 演进建议 | S1 |
| [S3](issues/S3-version-diff-ui.md) | Semantic | 版本切换与对比视图 | S1, U3 |
| [A1](issues/A1-auto-tag-from-recognition.md) | 助理 | 解析结果自动打标签 + 存量回填 | 无 |
| [A2](issues/A2-weekly-digest.md) | 助理 | 每周小结（范围材料汇总，指纹缓存） | 无 |
| [A3](issues/A3-custom-llm-provider.md) | LLM | 任意 OpenAI 兼容自定义供应商 | 无 |

依赖图（→ 表示 blocked by）：

```
R1 ─────────────────────────────────────────── (独立，最优先)
U1 ──┬─→ U2 ──→ (可与 U4/U5 并行)
     ├─→ U3 ──→ S3
     ├─→ U4
     └─→ U5
P1 ──┬─→ P2 (还需 U1)
     └─→ P3 (建议 U1 后)
S1 ──┬─→ S2
     └─→ S3 (还需 U3)
A1 / A2 / A3 ──────────────────────────────── (独立；与 U 系有弱领地交集，见看板)
```

## 4. 排期建议

- **第一波**（互不阻塞，可同时派）：R1、U1、P1、S1、A1、A2、A3。A 系与 U 系在 `webstatic/` 有弱交集，调度按看板领地提示切分或错峰。
- **第二波**（U1/P1/S1 落地后）：U2、U3、U4、U5、P2、P3、S2。
- **第三波**：S3（收尾，依赖 U3+S1）。
- 与前几轮相同：`ready-for-agent` 表示需求已就绪；并行 worker 领地隔离由调度协议负责（`docs/agents/parallel-dev.md`）。

## 5. 明确不做（本轮 Out of Scope）

- 前端框架重写 / 构建链（见 2.1 决策）
- 向量检索 / embedding 通道（开放问题，另立）
- Semantic Merge 自动合并、跨文档自动关联（沿 knowledge-workspace PRD）
- 多用户、云同步、移动端适配承诺
- 模板系统 + HTML/PDF 导出（原 MVP P1 承诺，本轮仍不排，避免战线过长；维护者可另立）
