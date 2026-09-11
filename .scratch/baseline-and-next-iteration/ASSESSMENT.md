# 开发基线与下一轮需求检查

日期：2026-09-11
Status: assessment-complete
基准：本地主检出 main `6caaef9`，包含检查开始时已有的未提交改动。

本文是检查结果与需求整理，不是已完成基线清理的声明，也不代表新产品 PRD 已冻结。

## 1. 已确认的需求边界

| 工作 | 定位 | 本轮确认 |
|---|---|---|
| 整理干净基线 | 开发基础工作，优先执行 | 保留并核对现有改动，补齐可复现环境、测试、安装/运行验证、文档与 issue 状态 |
| 视觉模型校验 | 开发迭代工具，不是产品需求 | 优先直接接视觉 LLM API；Agent harness 与模型 API 是不同层次的选择 |
| UI 视觉验收 | 开发验收之一 | 检查网页/应用截图；与自动化交互测试配合 |
| 内容视觉验收 | 开发验收之二 | 对照原稿与 Markdown、公式、表格、重建图；与确定性测试配合 |
| Obsidian 集成核查 | 现有产品能力核查 | 确认导出、增量、来源与用户修改保护，以及尚未连通的入口 |
| PDF 导入 | 新产品范围 | Web 上传、拆页解析、入库 |
| PDF 查询 | 新产品范围 | 搜索已导入 PDF 内容，并基于内容问答；用户明确两项 PDF 能力都要 |

“Honey / Cloud”已澄清为口述中的 agent harness 讨论，不作为额外工具名称；不需要再选定一个 harness 才能开展视觉校验。

## 2. 基线检查结果

### 代码与环境

- 当前源码测试：**351 passed，2 skipped，0 failed**。执行 `.venv/bin/python -m pytest -q --tb=short`，退出码 0；进度计数与日志见 [pytest.log](evidence/pytest.log)。两项跳过位于 Graphviz 可选能力测试。
- 初始 `.venv` 未安装 pytest/httpx 等检查依赖。本轮只补装本地检查依赖，没有修改产品代码、依赖声明或 uv.lock。报告环境包含 Python 3.13、pytest 9.1.1、httpx 0.28.1、reportlab 4.5.1、PyMuPDF 1.28.2、matplotlib 3.11.1。
- 测试通过不等于依赖配置完备：`dev` extra 没有声明测试所需 httpx，绘图回退依赖也需归整。下一步需要将正确的依赖集合写回配置并验证干净环境安装。
- `git diff --check` 通过。
- `main` 相对本地记录的 `origin/main` 领先 16 个提交；本次未 fetch，因此不是对远程最新状态的确认。
- 本机安装 Pi 0.85.1、OpenCode 1.18.20、Claude Code 2.1.206；本轮未启动这些 Agent 执行任务。
- `.env` 配置了 Kimi 与 DeepSeek key。只检查配置存在性，密钥未写入报告。

### 已复现的安装问题

使用 `uv build --wheel --out-dir /tmp/graph2note-baseline-wheel-20260911` 构建成功，但 wheel 文件中：

- `graph2note/notes/`：0 个文件。
- `eval/`：0 个文件。

将 wheel 解压到临时目录，移除 editable 安装的 import finder，导入结果为：

```text
graph2note.notes ModuleNotFoundError No module named 'graph2note.notes'
graph2note.webapp ModuleNotFoundError No module named 'eval'
```

原因：`pyproject.toml` 显式 packages 清单遗漏 notes 与运行时调用的 eval。应补齐打包内容并增加安装后启动验证；源码测试不能替代这项检查。

### 已有未提交工作

检查开始时存在：

- Kimi 网关注册及对应测试调整：`eval/gateway.py`、`tests/test_llm_settings.py`。
- macOS 应用：`macos/`、`scripts/build_macos_app.sh`、`docs/macos-app.md`、依赖与忽略规则调整。
- 工作台 PRD 概念稿引用和 `design/01-note_compiler_concept.html`。
- 新真实样本：`test-images/02-digitize-pipeline-increment.jpg`。
- `.env.swo`、`.env.swp` 编辑器交换文件：不要提交；需要加精确忽略或另行保留，不能把它们当成可公开文档。

本轮未提交、推送、删除或暂存这些已有工作。macOS 包未重新构建/启动验证，不能宣布桌面发布基线通过。

### 历史状态

26 份正式 issue 的 Status 都是 merged；旧 BOARD、部分验收勾选项和 PRD 进度未同步。源码测试通过不代表每条产品验收条件都完成。应按当前证据更新，不机械地将全部复选框勾上；质量评估、真实样本和旧提速质量回归欠账需要单独留存。

## 3. 开发视觉验收：直接 API 可行性

建议首版：**浏览器/应用截图与测试产物 → 独立视觉检查脚本 → JSON 问题报告 → 人工或开发 Agent 复核**。不新增产品页面、用户设置或用户调用流程。

| 方案 | 已确认能力 | 对本项目的判断 |
|---|---|---|
| 直接视觉 LLM API | Kimi 官方支持图片输入；本项目已有供应商网关，本轮两次 live 请求成功 | 首选；可以明确控制输入、次数、超时、输出 schema，复用 `.env` |
| Pi | 官方支持 `pi -p @screenshot.png`，也提供 JSON、RPC、SDK | 需要模型自主读文件/调工具时再考虑；目前不是必需依赖 |
| OpenCode | CLI `run` 附件与视觉模型输入；具体支持受客户端/模型版本限制 | 可作开发工作流外壳，单纯检查固定截图没有必要先接整套 harness |
| Claude Code | Read 可读图，print 模式支持结构化输出 | 已安装，可作为后续工具，但本轮没有验证其账号和模型配置 |

官方依据：[Kimi 图片输入](https://platform.kimi.com/docs/guide/use-kimi-vision-model)、[Pi README](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md)、[OpenCode CLI](https://opencode.ai/docs/cli/)、[OpenCode 附件](https://opencode.ai/v2/docs/attachments)、[Claude Code Read](https://code.claude.com/docs/en/tools-reference)、[Claude Code 程序化调用](https://code.claude.com/docs/en/headless)。选择直接 API 是结合项目现有代码作出的判断，不是这些工具的通用优劣排名。

### 本轮试验

- 独立临时文档库启动 Web；1440×1000 空 Library 页面加载成功，没有捕获到 pageerror。
- 使用 `kimi-k2.6`，每次最多 1400 输出 token、45 秒超时、不重试，总共 2 次请求。
- UI：真实 [Library 截图](evidence/library.png)，返回可核对的页面描述，没有报明显重叠/截断；耗时 9.70 秒，2279 total tokens。
- 内容：使用刻意构造的控制样例，原图为 `ALPHA -> BETA` 和 `E = m c^2`，候选 Markdown 改为 `GAMMA` 和 `c^3`；模型找出了两项差异。耗时 3.96 秒，759 total tokens。
- 总计 3038 total tokens。未配置/核对价格，未推算金额。
- 记录：[vision-probe.json](evidence/vision-probe.json)，[控制图片](evidence/content-control.png)，[候选 Markdown](evidence/content-control.md)。

这只证明传图、结构化输出和简单差异检查可用，不代表真实手稿识别率、完整 UI 可用性或生产验收质量达标。UI 截图不能替代交互测试，简单控制样例不能替代公式/表格/真实图形的评估集。

### 正式开发工具待明确的契约

- UI 与内容分别维护样例、输入格式、评分/问题类别、验收标准；不要混成单一“质量分”。
- 输出应包含严重度、截图区域或页码/块定位、源证据、候选证据、修复建议和不确定性。
- 固定模型/提示词版本、输入指纹、超时和调用预算；支持缓存与离线重放。
- 先作为辅助审查，在误报/漏报已量化前不以 LLM 单次判断作为唯一通过门槛。
- 内容轨后续样例覆盖真实手稿、公式、表格、箭头关系，以及重建图和 Markdown 的渲染截图。

## 4. Obsidian 集成现状

现有能力是**单向导出 Vault**，不是双向同步或 Obsidian 插件。

已存在并通过当前测试的能力：

- 文档 Markdown、原稿图片、附件与 frontmatter 溯源。
- 主题分类、MOC 索引、集合导航文件、时间和标签元数据。
- 增量导出：新增/更新/删除系统文件、无变化零写入、相对链接校验。
- 用户编辑/改名保护。注意：当前保护方式是将用户改动保留为备份文件，再生成系统受管路径，并不是将两份修改语义合并。

本轮另外用独立 fixture 文档库执行 3 次导出：首次生成 note/source/collection/MOC；第二次 added/updated/deleted/conflicts 全空；手工加入用户编辑后第三次报告冲突，并保留含该编辑的备份。见 [obsidian-smoke.json](evidence/obsidian-smoke.json)。未修改用户实际 Vault，也未在 Obsidian 桌面应用中验收显示效果。

关键缺口：

1. Web 没有全库 Obsidian 导出端点/按钮；现有 Web export 只下载单文档 Markdown+附件 ZIP。
2. Web 默认文档库为 `./.g2n-storage`，`notes-export` CLI 默认是 `storage`；macOS 默认又是 Application Support 路径。若不显式传 `--storage`，可能导出不到网页中的文档。
3. 默认导出链路使用规则分类；LLM 分类函数可注入，但普通 CLI 没有提供该选择，不能把“已有 LLM 适配器”理解为默认使用 AI 自动整理。
4. Python wheel 漏包使安装后的导出不可用，属于前述基线问题。

当前正确调用方式需显式指定真实文档库：

```bash
.venv/bin/python -m graph2note.cli notes-export --storage ./.g2n-storage -o /path/to/vault
```

## 5. PDF 两部分需求

### PDF 上传、解析与入库

可复用：`ingest` 的 PyMuPDF 拆页、页序、感知哈希去重、缺页线索、入库适配器。

仍需实现完整流程：

- Web 接收 PDF 与批任务状态；逐页成功/失败、重试和恢复。
- 将拆页、解析、入库串起来。现有 PDF CLI 主要生成页面与报告，入库适配器不传 recognizer 时只写“待解析”占位。
- 保存原 PDF、稳定的 PDF 文档身份、原始页序与页文档对应关系。`Page` 已有 `source_pdf/page_index`，但入库调用没有完整持久化这些来源字段，不能直接作为问答引用系统。
- 明确空白页、重复页、加密/损坏 PDF、部分失败、文件大小和页数限制。

### PDF 内容搜索与问答

当前未发现全文索引、检索/问答 API、引用回跳能力。这是新增产品功能，不是现有 PDF 拆页的一项开关。

建议拆为可独立验收的步骤：

1. 按 PDF/页/正文建立检索索引，先实现关键词搜索，显示命中片段和来源。
2. 基于检索内容回答问题，引用原 PDF 页码，点击可回到原文；无证据时明确说明，不能编造来源。
3. 文档修改、重新解析、删除后同步更新索引；内容版本与引用可追踪。

是否引入向量检索、跨 PDF 问答、纯文字 PDF 直接提取还是统一视觉解析、对话历史保存范围，都需要下一步 PRD 决定，暂不默认加入。

## 6. 推荐执行顺序与完成条件

| 顺序 | 工作 | 完成条件 |
|---|---|---|
| 0 | 收口现有未提交工作与仓库基线 | 每项已有改动有归属；敏感/临时文件不进入提交；依赖声明可复现；源码测试与安装后启动通过；macOS 单独验证；issue/BOARD/运行文档一致；形成可追踪的基线提交 |
| 1 | 开发视觉 QA 工具 | UI 与内容两条可重复命令，结构化证据、明确预算、离线回放；真实样例验证误报/漏报 |
| 2 | Obsidian 使用闭环 | 统一/明确文档库配置，Web 导出入口和冲突报告；真实 Vault 展示与引用验收 |
| 3 | PDF 导入 | 上传→拆页→解析→入库→打开原页，失败可恢复，来源可追踪 |
| 4 | PDF 搜索、问答 | 可检索、答案有页级引用、无证据不编造、删除/更新后索引一致 |

本轮到“检查与可行性验证”结束。未修改产品实现，未声称当前工作区已经干净；后续先完成第 0 项，再推进开发工具及产品 PRD。
