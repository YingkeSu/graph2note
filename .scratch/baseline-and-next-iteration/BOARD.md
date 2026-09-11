# BOARD：baseline-and-next-iteration

发布日期：2026-09-11
用户已确认 11 个切片及依赖关系，正式 issue 已发布到本地 tracker。

来源：[拆分草案](ISSUE-DRAFT.md)、[检查报告](ASSESSMENT.md)。草案保留审阅时原貌；发布状态以本看板及各 issue 为准。

## 发布与执行状态

- 已发布：11；已认领：4；已完成：0；验收通过待合并：4（01/06/04/08，2026-09-12 用户批准合并入本地 main）。
- 2026-09-11 调度：01→graph2note-10、04→graph2note-13、06→graph2note-11、08→graph2note-12 并行启动（04/06/08 在 03 归档前提前启动，已与 03 领地隔离）；reviewer=graph2note-14。
- 所有 issue 的 `ready-for-agent` 表示需求已准备好，不表示阻塞依赖已完成。
- 当前可立即开始：**01**。本次只发布，不认领或启动实现。
- 优先顺序：基线 01–03 → 开发视觉 QA 04–05 → Obsidian 06–07 → PDF 08–11。
- 技术依赖独立于排期：06、08 不依赖视觉 QA 工具才能运行，PDF 不依赖 Obsidian；08 完成后 09 与 10 可分别开展，11 依赖 10。
- 视觉 QA 是开发工具，不新增产品功能入口；PDF 导入、搜索与问答是产品需求。
- 首版范围沿用已确认草案：Obsidian 使用现有规则分类；PDF 先做关键词检索和单轮问答；不隐含双向同步、向量检索或长期对话历史。

## Issue 清单

| Issue | 类别 | Blocked by | Status |
|---|---|---|---|
| [01 恢复可复现的 Python 安装与运行基线](issues/01-reproducible-python-baseline.md) | 基线 | 无 | merging（验收通过 8121fda；graph2note-10 执行合并） |
| [02 统一文档库配置并验收 macOS 应用](issues/02-shared-library-macos-app.md) | 基线 | [01](issues/01-reproducible-python-baseline.md) | ready-for-agent |
| [03 归档已有工作并形成干净基线](issues/03-clean-baseline-release.md) | 基线 | [01](issues/01-reproducible-python-baseline.md)、[02](issues/02-shared-library-macos-app.md) | ready-for-agent |
| [04 建立 UI 截图视觉验收命令](issues/04-ui-visual-qa-command.md) | 开发工具 | [03](issues/03-clean-baseline-release.md) | merging（验收通过 f118f79） |
| [05 建立原稿与产出对照视觉验收命令](issues/05-content-visual-qa-command.md) | 开发工具 | [04](issues/04-ui-visual-qa-command.md) | ready-for-agent |
| [06 从 Web 导出 Obsidian Vault](issues/06-web-obsidian-vault-export.md) | Obsidian | [03](issues/03-clean-baseline-release.md) | merging（验收通过 130d986） |
| [07 展示 Obsidian 增量变化与冲突结果](issues/07-obsidian-incremental-conflict-report.md) | Obsidian | [06](issues/06-web-obsidian-vault-export.md) | ready-for-agent |
| [08 上传 PDF 并逐页解析入库](issues/08-pdf-upload-parse-library.md) | PDF | [03](issues/03-clean-baseline-release.md) | rebase 中（验收通过 49915f4；graph2note-12 rebase 到 6caaef9 后合并） |
| [09 PDF 批任务中断恢复与失败页重试](issues/09-pdf-job-recovery-retry.md) | PDF | [08](issues/08-pdf-upload-parse-library.md) | ready-for-agent |
| [10 搜索 PDF 内容并跳转命中原页](issues/10-pdf-content-search.md) | PDF | [08](issues/08-pdf-upload-parse-library.md) | ready-for-agent |
| [11 基于 PDF 内容问答并提供页级引用](issues/11-pdf-grounded-question-answering.md) | PDF | [10](issues/10-pdf-content-search.md) | ready-for-agent |
