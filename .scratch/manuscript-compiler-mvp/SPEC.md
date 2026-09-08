# Feature Specification: Manuscript Compiler MVP — 手写图片 → 结构化 Markdown

Status: ready-for-agent
Created: 2026-09-08
Revised: 2026-09-08 — 落实维护者评审决策（个人自用定位、流程图重建、语义化删除、三栏预览、保留至删除）
Input: 手稿/笔记/论文扫描 → 智能解析 → Document IR → Markdown（MVP 唯一输出，流程图重建为图片嵌入）→ 三栏编辑/预览/导出；P1 叠加 HTML/CSS 模板与 PDF
Platform: 个人自用本地部署（单用户、无鉴权、数据不出本机，仅解析时调用 LLM API）
配套文档: [PRD](./PRD.md)（产品背景、用户画像、路线图）

> 优先级说明：User Story 的 P1/P2/P3 表示「可独立交付的价值切片顺序」，与路线图的 P0/P1/P2 功能分层不是同一套编号。

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 上传手写图片，得到结构化 Markdown (Priority: P1)

用户上传一张单页手写笔记照片，系统自动预处理（转正、校正、裁剪）、经 Recognition Router 解析为 Document IR 并渲染为 Markdown。这是产品的核心价值切片，独立成立即为可用 MVP。

**Why this priority**: 没有这一步，产品不存在。所有后续能力（编辑、导出、模板、PDF）都以此为前提。

**Independent Test**: 上传固定的手稿测试图片，断言输出的 Markdown 具有正确的标题层级、列表结构与正文内容，全程无需手动配置。

**Acceptance Scenarios**:

1. **Given** 一张正拍的清晰手写笔记照片，**When** 上传并等待解析完成，**Then** 界面显示 Markdown，标题、列表、段落结构与原图语义一致
2. **Given** 一张横向拍摄的旋转照片，**When** 上传，**Then** 系统自动转正后解析，输出与正拍等价
3. **Given** 一张透视歪斜、光照不均的手机照片，**When** 上传，**Then** 预处理自动校正，解析不受拍摄条件明显影响
4. **Given** 一张中英文混排手稿，**When** 解析，**Then** 两种语言内容均被完整识别
5. **Given** 手稿中的流程箭头/框图，**When** 解析，**Then** 重建为图片并以 Markdown 图片语法嵌入，节点与连线方向可读
6. **Given** 手稿中被删除线/涂抹明确划掉的内容，**When** 解析，**Then** 该内容不出现在输出中

---

### User Story 2 — 对照校对、编辑与导出 (Priority: P1)

解析完成后，用户在三栏界面（原图 | Markdown 编辑 | 实时渲染预览）对照校对，直接编辑 Markdown 修正识别错误，复制文本或导出 `.md` 及其附件。

**Why this priority**: 「识别结果可编辑」是产品定位（Document Understanding 而非 OCR）的直接体现；EditRate 指标依赖此切片才能成立。

**Independent Test**: 解析完成后编辑 Markdown 文本，下载的文件包含编辑后内容；复制操作将完整 Markdown 写入剪贴板。

**Acceptance Scenarios**:

1. **Given** 解析完成，**When** 用户把误识别的「SAO」改为「SAC」并导出，**Then** `.md` 文件包含修改后的内容
2. **Given** 解析完成，**When** 点击复制，**Then** 剪贴板获得完整 Markdown 文本
3. **Given** 含流程图重建图片的文档，**When** 导出，**Then** 得到 `.md` 及其引用的全部图片附件
4. **Given** Markdown 中含公式与表格，**When** 编辑，**Then** 预览栏实时渲染出公式与表格
5. **Given** 编辑过但未导出的 Markdown，**When** 用户点击「重新解析」，**Then** 系统明确提示编辑内容将被覆盖

---

### User Story 3 — 失败可感知、可重试 (Priority: P2)

所有失败路径（无效文件、解析失败、超时、空白图片）都给出明确反馈，且不丢失用户已上传的原图。

**Why this priority**: 不阻塞核心价值验证，但直接决定产品可信度，须在 MVP 内完成。

**Independent Test**: 分别提交非法文件、模拟解析超时、提交空白图片，断言错误提示文案与重试入口，且原图仍展示。

**Acceptance Scenarios**:

1. **Given** 一个非图片文件（如 .txt），**When** 上传，**Then** 系统拒绝并提示支持的格式与大小上限
2. **Given** 解析服务超时或返回错误，**When** 等待结束，**Then** 界面显示失败原因与「重试」入口，已上传原图已保存在本机不丢失
3. **Given** 一张近乎空白的图片，**When** 解析，**Then** 返回空文档提示，而非报错或挂起

---

### User Story 4 — 印刷体扫描件走同一链路 (Priority: P3)

印刷文档（论文扫描、讲义）通过同一上传入口解析为 Markdown。MVP 阶段路由可恒走 Vision LLM 路径，允许印刷体质量相对次优；OCR 路径的引入由 Spike 2 结论决定。

**Why this priority**: 验证 router 接口设计的正确性（同一入口、可插拔策略），但质量优化非 MVP 目标。

**Independent Test**: 上传印刷体论文扫描页，输出结构合法的 Markdown（标题/段落/引用），质量不设硬指标。

**Acceptance Scenarios**:

1. **Given** 一页印刷论文扫描件，**When** 上传解析，**Then** 输出的 Markdown 通过 IR schema 校验且结构可读
2. **Given** 同一图片重复解析两次，**When** 比较两次输出，**Then** 渲染层输出确定（差异仅可能来自模型本身，渲染层逐字节一致）

---

### User Story 5 — 本机文档库管理 (Priority: P2)

解析过的文档（原图、IR、Markdown 最新版、附件）保存在本机；用户可查看历史列表、重新打开继续编辑、删除任意文档。

**Why this priority**: 「保留至用户删除」要求数据生命周期由用户掌控；同时保证编辑成果刷新页面不丢失。

**Independent Test**: 解析并编辑一个文档，刷新页面后从列表重新打开内容仍在；删除该文档后列表项与本机数据均消失。

**Acceptance Scenarios**:

1. **Given** 已有若干解析文档，**When** 打开文档列表，**Then** 显示各文档（缩略图/时间）并可打开继续编辑
2. **Given** 某文档，**When** 用户删除并确认，**Then** 原图、IR、Markdown 及附件全部从本机移除

---

### Edge Cases

- 图片超过大小上限（10MB）或分辨率过低 → 拒绝并提示；分辨率偏低时提示可能影响质量
- EXIF 方向标记与图片实际内容方向矛盾 → 以内容判定为准
- LLM 返回不符合 IR schema 的内容（非法 JSON、未知 block 类型）→ 重试/降级并最终给出明确错误，绝不能让非法 IR 进入渲染层
- VLM 无法从手稿流程图中提取结构化语义 → 降级为裁剪原图嵌入，解析不失败
- 删除线/涂改判断模糊（波浪线、轻划、半成品划线）→ 保守保留内容交用户处理，不激进删除
- 正文中出现 Markdown 特殊字符（`*`、`#`、`_`、反引号）→ 渲染层必须转义，防止结构被意外注入
- 手稿含大段涂改、重叠书写、极小字号 → 允许质量下降，但不得崩溃或挂起
- 空文档（零 block）→ 输出空 Markdown 与提示
- 导出的 `.md` 引用的附件必须全部随附；引用缺失时在界面上标出
- 预览渲染失败（如不完整公式）→ 预览区显示错误占位，不影响编辑栏
- 用户连续快速多次点击「重新解析」→ 请求防抖/进行中禁用
- 中文标点与全角字符 → 原样保留，不做半角化改写

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 接受 JPG/JPEG/PNG 格式的单页图片上传，并拒绝其他格式并给出提示
- **FR-002**: 系统 MUST 自动检测并纠正图片方向（EXIF 与内容判定结合），用户无需手动旋转
- **FR-003**: 系统 MUST 在解析前自动执行透视校正、页面边缘裁剪与对比度优化；预处理与识别为两个独立阶段
- **FR-004**: 所有解析请求 MUST 经由 Recognition Router 统一入口；MVP 允许路由实现恒走 Vision LLM 路径，但上游不得绕过该接口
- **FR-005**: 解析层 MUST 输出通过 schema 校验的 Document IR；block 类型全集为 `heading / paragraph / list / formula / table / code / quote / image / diagram / flow`；未通过校验的 IR MUST NOT 进入渲染层
- **FR-006**: Markdown Renderer MUST 为确定性纯函数：同一 Document IR 的两次渲染结果逐字节一致
- **FR-007**: 系统 MUST 将 heading 映射为 ATX 标题、list 映射为 Markdown 列表、paragraph 按原始阅读顺序分段
- **FR-008**: formula block MUST 渲染为 LaTeX 数学定界符语法（行内 `$…$`、独立 `$$…$$`）；识别质量不作 MVP 验收项（P1 优化）
- **FR-009**: diagram/flow block MUST 携带结构化语义（节点、连线、方向）并由确定性绘图工具链（matplotlib 或同类）渲染为图片嵌入 Markdown；语义提取失败时 MUST 降级为裁剪原图嵌入，MUST NOT 产生乱码文本或导致解析失败
- **FR-010**: 界面 MUST 三栏展示原图（预处理后）、可编辑 Markdown 与实时渲染预览（预览支持公式与表格渲染）
- **FR-011**: 用户 MUST 能够编辑 Markdown 并导出编辑后内容：复制到剪贴板（纯文本）、下载 `.md` 及其引用的全部附件
- **FR-012**: 系统 MUST 提供「重新解析」操作，复用已上传图片；覆盖用户编辑前 MUST 明确提示
- **FR-013**: 系统 MUST 对无效输入、解析失败、超时给出用户可理解的错误信息，并提供重试入口
- **FR-014**: 每个文档的原图、IR 与最新版 Markdown MUST 持久保存于本机，刷新页面不丢失
- **FR-015**: 单文件大小上限 10MB（JPG/JPEG/PNG），超出拒绝并提示
- **FR-016**: 文档（原图、IR、Markdown、附件）保留至用户主动删除；删除 MUST 移除全部关联数据
- **FR-017**: Spike 与 MVP 的 LLM 调用经 opencode go 网关（OpenAI 兼容 `chat/completions` 端点；认证密钥存于本机 `.env`，已 gitignore；接入与实测记录见 `docs/llm/opencode-go.md`）。视觉模型候选为 `glm-5.3-flash` 与 `deepseek-v4-flash-vision-exp`（均已冒烟验证，Spike 1 对比定夺）。若均不达标，MUST 可替换供应商而不改解析层契约；MUST NOT 使用以用户输入训练模型的 muse 系列
- **FR-018**: 解析 MUST 语义化删除：被删除线/涂抹明确废弃的内容不出现在输出中；判断模糊时 MUST 保守保留
- **FR-019**: 系统 MUST 提供本机文档列表（查看历史文档、打开继续编辑、删除）
- **FR-020**: 绘图工具链 MUST 确定性渲染：同一 diagram 语义产出同一图片

### Key Entities *(include if feature involves data)*

- **Image（输入图片）**：用户上传的单页文档图像；属性：原始文件、格式、尺寸、方向、预处理后版本
- **Document IR（文档中间表示）**：系统的中心数据契约；`document_type` + 有序 block 序列；解析层唯一合法产物，渲染层唯一合法输入；有 schema 可校验
- **Block（内容块）**：类型化语义单元（heading/paragraph/list/formula/table/code/quote/image/diagram/flow），携带层级、文本、LaTeX、节点/连线等语义字段；不携带任何表现样式；diagram/flow block 以结构化语义（nodes/edges）而非图片区域表达
- **Markdown Document**：IR 经确定性渲染的产物；用户可编辑；导出格式
- **Attachment（附件）**：文档的图片资产（流程图重建产物、降级裁剪图）；以相对路径被 Markdown 引用；随文档持久化、随删除移除
- **DocumentRecord（文档记录）**：一次解析及其后续编辑的本机持久化单元：原图（预处理前后）、Document IR、最新版 Markdown、附件列表；生命周期止于用户删除
- **Recognition Route（解析路由）**：Router 的可插拔策略（MVP: Vision LLM 直出 IR；预留 OCR→LLM、Hybrid/Fusion）
- **解析任务（Parse Job）**：一次「图片 → Markdown」的处理过程；状态：已上传 → 预处理 → 解析 → 渲染 → 完成/失败

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 在 30–50 张真实手稿评估集上，EditRate（用户需编辑的字符数 / 总字符数）< 5%（主指标）
- **SC-002**: 结构正确性：人工抽检中标题层级、列表嵌套、段落划分与原稿语义一致（个人自用，人工评审通过即可，不设百分比硬门槛）
- **SC-003**: 公式输出为语法合法、可被 LaTeX 引擎编译的代码（合法率 100%）；转写正确率属 P1 优化目标
- **SC-004**: 渲染层确定性：同一 IR 重复渲染输出逐字节一致（回归测试 100% 通过）
- **SC-005**: Spike 1（Vision LLM 直转质量）与 Spike 2（OCR vs Vision LLM 分界）完成并产出路由策略结论
- **SC-006**: 评估集中流程图样本重建为节点/连线可读的图片；语义提取失败样本降级为裁剪原图，全程无乱码输出

## Assumptions

- 个人自用本地部署：单用户、无登录鉴权（仅本机访问）、数据不出本机（解析时调用 LLM API 除外）；不考虑防滥用、限流、审计、并发扩展
- MVP 提供 Web 界面（桌面浏览器优先），移动端仅要求可用，不做专门优化
- 多页文档由用户按页分别处理（P2 才支持多页合并）
- 评估集（30–50 张真实手稿，含手写笔记、印刷扫描、公式、中英混排、流程图样本）由项目维护者提供；gold Markdown 由 AI 辅助标注 + 人工校对，以 fixtures 形式入库
- 手稿语言以中文及中英混排为主，其他语言不作承诺
- HTML/CSS 渲染、模板系统、PDF 导出属 P1；本 spec 仅要求 IR/renderer 契约为其预留扩展点
- LLM 经 opencode go 网关调用（$10/月订阅含额度；2026-09-08 已用 `test-images/` 手稿实测视觉链路可用，文档 `docs/llm/opencode-go.md`）
