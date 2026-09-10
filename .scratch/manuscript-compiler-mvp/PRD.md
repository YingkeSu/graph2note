# PRD：Manuscript Compiler MVP — 手写图片 → 结构化 Markdown

Status: ready-for-agent
Version: v0.3
Created: 2026-09-08
Revised: 2026-09-08 — 落实维护者评审决策：个人自用本地平台定位、流程图重建进 MVP、语义化删除、三栏实时预览、数据保留至用户删除
Revised: 2026-09-10 — 新增 P2：LLM 供应商选择（网关注册表 seam 已随 DeepSeek 备援落地）
Phase: Concept / MVP Definition

> 一句话：**Manuscript Compiler 是一个基于多模态文档理解的手稿电子化工具，将手写笔记、草稿和扫描文档解析为结构化中间表示（Document IR），并自动生成可编辑 Markdown；模板系统在核心链路稳定后进一步渲染为 HTML/CSS 与 PDF。**

## Problem Statement

学生、科研人员、内容创作者的大量知识仍以手写形式存在：课堂笔记、草稿纸推演、白板讨论、论文手稿。现有 OCR 工具只解决「图片 → 字符」，输出扁平文本，丢失了标题层级、列表结构、数学公式、箭头流程、框选强调等语义。用户拿到 `模型 CNN Transformer Mamba` 这样的字符堆，真正需要的是带结构的可编辑文档，于是仍要花大量时间手工重排——电子化的成本没有真正降下来。

用户要的不是字符识别（OCR），而是文档理解（Document Understanding）。

## Solution

这是一个**个人自用的本地部署平台**：单用户、无登录、数据全部留在本机，不设防滥用 / 限流 / 审计等多人系统考量。

用户上传一张单页图片（手写笔记 / 印刷扫描 / 手机照片），系统自动完成：

```
预处理（旋转/透视/裁剪/对比度）
  → Recognition Router（Vision LLM 优先，OCR 路径预留）
  → Document IR（结构化中间表示）
  → Markdown Renderer（确定性渲染；diagram/flow 重建为图片嵌入）
  → 三栏界面（原图 | 可编辑 Markdown | 实时渲染预览）
  → 复制 / 导出 .md + 附件
```

解析结果与用户编辑持久保存在本机，直至用户主动删除。MVP 的唯一输出格式是 Markdown。核心原则：**Content ≠ Presentation** —— 系统只还原内容语义（标题、列表、公式、关系），表现样式（字体、版式、模板）完全交给后续的模板层，不进入内容管线。

## User Stories

### MVP（P0）

1. 作为学生，我想上传一张手写课堂笔记照片，以便得到结构化 Markdown 笔记而不是一坨 OCR 文本。
2. 作为用户，我想上传 JPG/JPEG/PNG 单页图片，以便覆盖手机拍照和扫描仪两种来源。
3. 作为用手机横拍笔记的用户，我希望系统自动检测并纠正图片方向，以便不必手动旋转后再上传。
4. 作为拍摄角度歪斜的用户，我希望系统自动做透视校正、边缘裁剪和对比度优化，以便识别质量不受拍摄条件影响。
5. 作为学生，我希望手写标题被识别为对应层级的 Markdown 标题，以便笔记有大纲和导航结构。
6. 作为学生，我希望手写列表和缩进被还原为 Markdown 列表，以便层级关系不丢失。
7. 作为用户，我希望正文段落被完整识别、按原始阅读顺序分段，以便不需要手工重排段落。
8. 作为科研人员，我希望中英文混排内容被正确识别，以便双语笔记无需分别处理。
9. 作为用户，我希望在三栏界面中并排看到原图、可编辑 Markdown 与渲染预览，以便快速对照校对。
10. 作为用户，我想直接编辑识别出的 Markdown，以便修正个别识别错误（如 SAC→SAO）而不必重新扫描。
11. 作为用户，我想一键复制 Markdown 到剪贴板，以便粘贴进 Obsidian/Notion 等工具。
12. 作为用户，我想下载 `.md` 文件，以便归档到自己的笔记库。
13. 作为对结果不满意的用户，我想点击「重新解析」，以便用当前管线重试而不必重新上传。
14. 作为上传了无效文件的用户，我希望得到明确的错误提示（格式/大小），以便知道如何修正。
15. 作为用户，当解析失败或超时时，我希望被告知原因并能重试，以便不丢失已上传的工作。
16. 作为用户，我希望被删除线/涂抹明确划掉的内容不出现在输出中，以便不必逐页手工清理废弃文字。
17. 作为用户，我想在第三栏看到 Markdown 的实时渲染预览（公式、表格、流程图），以便不切换工具就能确认效果。
18. 作为用户，我希望手写流程/箭头图被重建为图片并嵌入 Markdown，以便 A→B→C 的关系直接可读。
19. 作为用户，我想在本机查看历史解析文档的列表并删除不需要的，以便自己掌控数据留存。

### P1

20. 作为科研人员，我希望数学公式被转换为 LaTeX（`$…$` / `$$…$$`），以便在支持 LaTeX 的编辑器中直接使用。
21. 作为学生，我希望手写表格被识别为 Markdown 表格，以便保留行列关系。
22. 作为用户，我希望解析结果通过 IR 渲染为 HTML 并按模板预览，以便看到接近成品的排版效果。
23. 作为用户，我想从预置模板（如「北航课程笔记」「学术论文」「简洁 Markdown」）中选择样式，以便同一份 Markdown 渲染出不同版式。
24. 作为用户，我想把 HTML+CSS 编译导出为 PDF，以便打印和提交。
25. 作为科研人员，我想解析印刷体论文扫描件并得到不差于手写体的质量，以便系统覆盖文献数字化场景。

### P2

26. 作为用户，我希望系统按文档类型自动路由解析策略（手写→Vision LLM，印刷密集→OCR，公式→Formula OCR），以便各类型都获得最优质量。
27. 作为用户，我希望草图/示意图（非流程结构的图形）也能被重绘或清晰留存，以便图形类内容全部可用。
28. 作为用户，我希望圈选、下划线、插入箭头等更多手写编辑语义被理解并生效，以便手写修改语义完整落地（删除线已进 MVP）。
29. 作为高频用户，我希望系统学习我的书写风格和符号习惯，以便识别越用越准。
30. 作为用户，我想一次上传多页文档并保持页序合并输出，以便整本笔记电子化。
36. 作为用户，我想选择 LLM 供应商与各用途模型（解析视觉 / IR 文本 / 图形提取 / 分类归纳），并看到当前生效通道及其可用性状态，以便某条通道不可用（如 opencode 故障）或性价比变化时，无需改代码、无需重启即可切换。

### P1 增补（2026-09-08 评审：去重/缺页/交叉验证/提速）

31. 作为用户，我希望重复上传/多次扫描的同一页被系统识别为同一文档而非新建条目，以便文档库不出现重复
32. 作为用户，我希望系统在有线索（页码、日期标题、系列连续性）时提示疑似缺页，以便及时发现扫描遗漏
33. 作为用户，我希望系统对识别结果做双模型交叉验证并标出分歧，以便漏识别与误识别可见、可信
34. 作为用户，我希望单页解析明显提速（初始目标端到端 P95 ≤ 60s），以便批量整理不用久等
35. 作为用户，我希望直接上传扫描 PDF 并自动按页拆分进入管线，以便扫描仪产出无需手工转图

## Implementation Decisions

- **四层管线**：输入层（上传 + 预处理）→ 智能解析层（Recognition Router）→ Document IR → 格式化输出层（Renderer：Markdown / HTML / PDF）。层间只通过数据契约通信。
- **技术栈：Python 全栈**（3.12+；Web 层 FastAPI、测试 pytest、预处理 Pillow/OpenCV、绘图 matplotlib/graphviz 按 Spike 结论）——绘图工具链的决策使渲染层与管线同语言，无跨语言契约。
- **Document IR 是系统的中心契约**：解析层的目标产物、渲染层的唯一输入。新增输出格式 = 新增 renderer，不改解析层；改进识别 = 只改解析层，不动渲染。这是对原始草图「图片→Markdown 直转」的最大架构修正。
- **IR 为带类型的 block 序列**，每个 block 携带语义字段。块类型第一版全集：`heading / paragraph / list / formula / table / code / quote / image / diagram / flow`。契约形态（来自设计讨论，字段以实现期 schema 为准）：

  ```json
  {
    "document_type": "note",
    "blocks": [
      { "type": "heading", "level": 2, "text": "状态空间模型" },
      { "type": "paragraph", "text": "…" },
      { "type": "list", "items": ["CNN", "Transformer", "Mamba"] },
      { "type": "formula", "latex": "\\dot{x}=Ax+Bu" },
      { "type": "diagram", "nodes": [{"id": "a", "label": "方案A"}], "edges": [{"from": "a", "to": "b", "label": "实验"}] }
    ]
  }
  ```

- **Recognition Router 是统一入口接口**：MVP 落地 Route A（Vision LLM 直接输出 IR）；Route B（OCR → LLM 结构化）与 Hybrid（分类器 + Formula OCR + Fusion/Judge）是路由的后续策略。MVP 允许路由实现退化为「恒走 A」，但上游调用必须经 router，不得绕过。**Spike 2 已落地并测量（2026）**：实现 `RouteBRouter`（OCR+文本 LLM 结构化）与 `AutoRouter`（特征路由，默认 A）；在 30 页评估集上 Route A 全面占优（EditRate 0.768 vs 0.865，24/30 页更优，含公式/手写/混排/图示/涂改全部类目），故默认**恒走 Route A**；仅当输入 OCR 平均置信度高分（≥55，判为清印刷）且以纯文本为主时才切 Route B（合成清中文印刷样本 EditRate 0.114 优于同路径公式页；公式/符号页仍应走 A）。详细对比见 `eval/reports/route-b-ocr-vs-vlm-summary.md`。
- **LLM 通道（Spike 与 MVP）**：经 opencode go 网关调用，接入文档落在 `docs/llm/opencode-go.md`，密钥在本机 `.env`（已 gitignore）。已实测两个视觉模型：`glm-5.3-flash` 与 `deepseek-v4-flash-vision-exp`（均通过本仓库手稿样本 `test-images/` 冒烟验证，调用参数见接入文档）；Spike 1 对两者做定量对比，若均不达标则引入其他供应商（解析层契约不变）。禁止使用会以用户输入训练模型的 muse 系列。
- **LLM 供应商选择（P2，user story 36；seam 已就绪）**：网关传输层已收敛为单一注册表 seam——端点/认证 key/session 头/模型名映射在 `post_gateway` 一处按 `GRAPH2NOTE_GATEWAY` 解析（2026-09-10 DeepSeek 官方 API 备援已落地：`opencode | deepseek`，文档 `docs/llm/deepseek.md`）。供应商选择功能在该注册表上扩展：新增供应商 = 新增注册项 + 模型名映射，调用方模型名不变；用途级模型选择沿用既有 `GRAPH2NOTE_*_MODEL` env 缩并暴露为 Web 设置；通道可用性探针复用会话直出验证的极小探针思路。首版为**手动选择**（.env / 设置界面），自动故障转移与多供应商并跑不承诺；单用户本地定位下不涉及供应商账号池管理。
- **语义化删除**：解析 prompt 明确指示不输出被删除线/涂抹明确废弃的内容；判断模糊时保守保留（宁可漏删交用户处理，不可误删正文）。系统化的手写编辑语义保证与评测留在 P2。
- **扫描 PDF 接入与页级去重（P1 增补）**：扫描 PDF 按页拆分为图片进入管线（保留页码可追溯）；感知哈希（pHash/dHash）做页级近重复检测，同页多次扫描/拍摄合并为同一 DocumentRecord 的候选版本（默认取最新、其余版本留存可查）。缺页检测为 best-effort——仅利用可检测线索（页码、日期标题、系列连续性）给出警告，无线索时不做完整性声明。
- **识别交叉验证（P1 增补）**：双模型独立解析（`glm-5.3-flash` 与 `deepseek-v4-flash-vision-exp`）后 diff 两份 IR：双侧一致→高置信；单侧出现→疑似漏识别；不一致→分歧块标记给用户审核；另做单文档内近重复块检测。双倍调用成本在个人自用定位下可接受。
- **性能预算（P1 增补）**：单页端到端（上传→可编辑 Markdown）初始目标 P95 ≤ 60s，基线先行实测；提速路径：非推理/低 token 输出模式、prompt 约束 JSON 直出、预处理与调用并发、同图缓存。
- **预处理是解析前的固定独立阶段**：方向判定与旋转、透视校正、边缘裁剪、对比度优化。与识别解耦，便于单独测试与替换。
- **Markdown Renderer 是纯确定性函数**：同一 IR 必产出同一 Markdown（文本与生成的图表均可复现）。手稿中的流程/箭头图**不降级为占位**：diagram block 携带结构化语义（节点、连线、方向），渲染层用确定性绘图工具链（matplotlib 或同类，选型实现期定）重建为图片，以相对路径嵌入 Markdown；VLM 无法提取结构化语义时降级为裁剪原图嵌入，绝不产生乱码文本。
- **Formula/table 的契约从第一天进入 IR 和 renderer**（避免 P1 时改契约），但识别质量不作为 MVP 验收项（对应优先级表中的 P1）。
- **PDF 只是导出格式**，不是核心数据格式：HTML + CSS → PDF 引擎（如 Chromium headless），路径与核心管线分离（P1）。
- **MVP UI**：三栏（原图 | 可编辑 Markdown | 实时渲染预览，预览支持公式与表格），底部操作区：重新解析 / 复制 / 导出（.md + 附件）；另设最简文档列表页（查看历史、打开继续编辑、删除）。为模板选择器预留位置。
- **本地持久化**：每个文档在本机保存原图（预处理前后）、Document IR、最新版 Markdown 与附件，保留至用户删除；不做定期清理，无隐私合规负担（数据不出本机，仅解析时调用 LLM API）。
- **附件机制**：流程图重建产物（及降级时的裁剪原图）存为文档的 assets；导出为 `.md` + assets 目录；复制到剪贴板仅复制文本。
- **输入范围**：JPG/JPEG/PNG 单页图片，单文件 ≤ 10MB（超出拒绝并提示）；Word、多页 PDF、实时摄像头不在 MVP。
- **质量指标**：Content Accuracy（正文）、Structural Accuracy（结构）、Formula Accuracy（LaTeX）、**EditRate = 编辑字符数 / 总字符数（目标 < 5%）**。EditRate 是主指标——它直接度量「用户还要改多少」。测量方法：评估 harness 对 gold Markdown 与 AI 输出做字符级 diff，将插入/删除/替换操作折算为编辑字符数后归一化。

## Testing Decisions

新系统没有既有 seam，需要从最高处建立三个 seam（实现前应与维护者确认）：

1. **Renderer seam（最高价值）**：`Document IR → Markdown` 是纯函数。测试 = IR fixture 进、期望 Markdown 字符串出，覆盖全部 block 类型与边界（空文档、嵌套列表、Markdown 特殊字符转义、diagram block 的图片引用与 assets 落盘）。diagram 重建（nodes/edges 语义 → 图片）单独作确定性渲染测试。不 mock、不触网、确定性可回归。
2. **IR schema seam**：解析层输出的 IR 必须通过 schema 校验才能进入渲染。解析层（Vision LLM 调用）的测试用**录制的真实 LLM 响应作为 golden files**，测路由决策与 IR 合法性，CI 中不 live 调用模型。
3. **管线 seam**：图片上传 → Markdown 输出的端到端测试，LLM 以 stub 替换，验证层间装配与错误传播（无效文件、超时、空结果）。

另有**评估 harness（非 CI、人工触发）**：30–50 张真实手稿的标注集，跑 Vision LLM 直转与 OCR+LLM 两条路径，计算 EditRate 等四项指标——这同时就是 Spike 1/2 的执行载体。评估集图片由维护者提供，gold Markdown 由 AI 辅助标注 + 人工校对，以 fixtures 形式入库。

个人自用平台：不做并发、安全、防滥用类测试；端到端仅覆盖单用户主流程。

好测试的标准：只测外部行为（输入→输出），不测实现细节；renderer 不感知 prompt，router 测试不感知 prompt 文本；预处理用合成变换图（已知旋转角/透视矩阵）验证可自动定标。无既有测试先例（greenfield）。

## Out of Scope（MVP）

- Word、多页 PDF、视频、实时摄像头输入（多页文档为 P2）
- HTML/CSS 渲染、模板系统、PDF 导出（P1，契约先留好）
- 公式 LaTeX 与表格的**质量承诺**（类型契约在 MVP，质量优化 P1）
- 草图/示意图（非流程结构）的重绘（P2；MVP 流程图重建 + 裁原图降级已覆盖结构类图形）
- 手写编辑语义的**系统化保证与评测**（删除线的语义化删除已进 MVP；插入箭头/圈选等 P2）
- 用户风格学习（P2）
- 多用户、账号、鉴权、云同步、协作、防滥用（个人自用本地平台，不设此类需求）
- 移动端 App（响应式 Web 即可）
- 缺页检测的**完整性保证**（无页码/日期等线索时物理上无法发现缺页，系统只做 best-effort 预警）
- 笔记分类归纳与 Obsidian 呈现（独立 feature：`notes-organizer`，见其 PRD）

## Further Notes

**三个 Spike 先于功能开发**（均可先以 CLI 形态执行——图片进、Markdown 出，UI 在 Spike 1 给出质量结论后再动工；评估 harness 直接复用）：

- **Spike 1**：Vision LLM 能否直接解决？30–50 张真实手稿跑 `Image → Vision LLM → Markdown`（经 opencode go 网关，起始素材已入 `test-images/`），看 EditRate。若足够好，MVP 不需要传统 OCR。
- **Spike 2**：什么时候 OCR 更好？`Vision LLM` vs `OCR + LLM`，分维度比较：手写体 / 印刷论文 / 公式 / 中英混排 / 小字。结论决定 Router 策略。**（已完成，2026）**：Route A 在 30 页手写/图示/公式评估集上全面占优，默认恒走 A；Route B 的适用区间窄——仅清印刷、纯文本为主（OCR 高置信）的文档，公式/符号与手写页一律 A。数据见 `eval/reports/route-b-ocr-vs-vlm-summary.md`，Router 策略已回写本条与「Recognition Router」段落。
- **Spike 3**：流程图重建路径是否成立？用 `A→B, A→C→D` 类流程手稿测试 VLM 能否稳定提取 nodes/edges 结构语义，以及 matplotlib（或同类）重建图的可读性；提取失败率决定裁原图降级的触发频率。

**已决策**（2026-09-08 与维护者确认）：个人自用本地平台定位；数据保留至用户删除；语义化删除进 MVP；三栏界面含实时渲染预览；流程图以 matplotlib（或同类）重建而非占位；Spike 与测试的 LLM 走 opencode go 网关（`OPENCODE_API_KEY` 在 `.env`，接入文档 `docs/llm/opencode-go.md`）。

**开放问题**（不阻塞 MVP 开发，实现期决策）：

- 视觉模型选型：候选 `glm-5.3-flash` 与 `deepseek-v4-flash-vision-exp`（均已实测可用），Spike 1 以 EditRate 定量对比；均不达标则换/加供应商
- 绘图工具链选型（**已由 Spike 3 决定，2026-09-08：graphviz/dot 为主，matplotlib 为依赖无关回退**）：对 10 张合成+2 张真实流程图语义，matplotlib 手写分层布局与 graphviz dot 均满足确定性（同一语义两次渲染逐字节一致，FR-020）；graphviz 布局零节点重叠（含回流/环）、连线交叉为 0，而手写分层布局在环上引入少量重叠（约 0.3 节点对/图）；两方案中文标签均无乱码（macOS graphviz 经 fontconfig 命中 Arial Unicode MS）。graphviz 唯一代价是需系统安装 `dot` 二进制，故 issue 05 建议 graphviz 可用则用、否则回退到 spike3 自带的 matplotlib 分层渲染器（接口一致 `render(diagram,out_path)`）。详见 handoff 04 与 spike3/report.md。
- 手稿语言范围（中文为主 / 中英混排 / 含少量其他语言）

**目标用户**：学生（课堂笔记、公式整理、复习资料）、科研人员（草稿、白板归档、文献数字化）、内容创作者（手稿转文章）。
