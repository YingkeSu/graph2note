# 基线整合报告（clean baseline release）

日期：2026-09-12
Status: baseline-committed
基准 commit：`32fe1d3`（main，本地；未 push）
本文是 issue 03「归档已有工作并形成干净基线」的整合证据。来源文档 `ASSESSMENT.md`、`ISSUE-DRAFT.md` 保持原貌，不被本报告修改或关闭。

## 1. 每项修改的归属（AC1）

基线起点为 main `6caaef9`（上一阶段收官）。检查开始时未提交的改动已逐项归档，无未知来源改动被丢弃：

| 原未提交改动 | 归属 commit |
|---|---|
| macos/、scripts/build_macos_app.sh、docs/macos-app.md、pyproject macos extra、uv.lock、.gitignore(build/dist/.env.sw?) | `16946be` feat(macos) |
| eval/gateway.py（Kimi 通道）、tests/test_llm_settings.py | `25117d7` feat(gateway) |
| .scratch/knowledge-workspace/PRD.md、design/01-note_compiler_concept.html | `ec0192b` docs(knowledge-workspace) |
| .scratch/baseline-and-next-iteration/（ASSESSMENT/BOARD/ISSUE-DRAFT/11 issue/evidence） | `92c3e8a` docs(baseline) |
| test-images/02-digitize-pipeline-increment.jpg（新样本） | `e413dfb` chore(test-images) |

后续经评审合并入 main 的 issue 分支：

| issue | 分支 | merge commit |
|---|---|---|
| 01 可复现安装基线 | ao/graph2note-10/01-… | `493e6ec` |
| 06 Web Obsidian 导出 | ao/graph2note-11/root | `e93e4d7` |
| 04 UI 视觉 QA | ao/graph2note-13/root | `19a3c9e` |
| 02 统一文档库配置 | ao/graph2note-10/02-… | `1993430` |
| 05 内容视觉 QA | ao/graph2note-13/root | `fca91de` |
| 01–06 handoff 收集 + Status merged + BOARD 同步 | — | `32fe1d3` |

## 2. 密钥/环境/交换文件不入提交（AC2）

- `.env` 精确忽略（`.gitignore` 既有）；`.env.sw?`（vim 交换文件）在 `16946be` 增加精确忽略，本机保留。
- `git ls-files` 无任何 `.env*`；`git diff` 扫描无硬编码密钥/凭证。
- 未做破坏性清理：旧文档库目录（`.g2n-storage`、`storage`、Application Support 下既有 43 篇）与用户数据均未移动/覆盖（见 issue 02 AC5 与 handoff）。

## 3. 状态分类（AC3，不机械勾选）

### 已验收（本轮 01–06，均 merged + pytest 绿）
- 01 可复现安装基线、02 统一文档库配置、04/05 UI/内容视觉 QA、06 Web Obsidian 导出；每项 AC 证据见各自 handoff（`handoffs/01…06`）。

### 历史文档滞后（保留不勾选）
- `manuscript-compiler-mvp/` 与 `notes-organizer/` 的 PRD/SPEC/BOARD：上一阶段 20/20 merged，但部分 issue 的 AC 勾选、BOARD 状态与 PHASE-SUMMARY 存在滞后；本轮**不**机械勾选这些历史验收项。

### 仍需补验（质量欠账）
- EditRate 精细校对（gold 为 AI 草拟 + 人工校对未完成）。
- 预处理 perspective 校正 bug（`graph2note/preprocess.py::_homography` 解错线性系统，全页扫描件 warp 成黑图；有独立 handoff `fix-black-preprocess.md`，尚未并入主线）。
- 印刷样本 + AutoRouter 默认策略的实证（issue 08 历史结论待真实印刷证据）。
- macOS 应用真实 UI 点击验收（后端/启动/持久化已验，窗口内交互仍为手工路径）。

## 4. 测试与安装检查记录（AC4）

在基线 commit `32fe1d3` 上完成：

- **全量源码测试**：`424 passed, 0 failed, 0 skipped`（退出码 0）。
  - 0 skip 因本机 `dot`(graphviz 14.1.2) 与 `tesseract`(5.5.2) 均在且 `diagram` extra 就绪；缺失时的跳过点记录在 `docs/setup.md`（test_ocr 的 tesseract、test_diagrams 的 graphviz、test_ingest_pdf 的 pymupdf）。
- **wheel + 独立环境验证**：`uv build --wheel` 退出码 0；独立 venv 装 `whl[all]` 退出码 0；隔离目录（无源码路径/editable finder）下「运行时导入 → Web 启动(/api/config) → CLI IR→MD」三步 PASS。
- **macOS 应用**（issue 02 验收记录）：`./scripts/build_macos_app.sh` 退出码 0；隔离 `GRAPH2NOTE_APP_SUPPORT` 下启动/退出/重启、文档与模型设置持久化通过；真实库 43 篇未被触碰。
- **环境**：Python 3.13.13 / uv 0.11.17 / pytest 9.1.1 / arm64；pydantic 2.13.5、fastapi 0.141.1、pymupdf 1.28.2、matplotlib 3.11.1。
- **工作区**：`git status` clean（仅 `.env`/`.env.swo` 等本机忽略文件，未跟踪）。

## 5. CI 状态（AC5）

仓库**无 CI checks**。按 issue 03 口径：本地验收与基线提交完成即停；不循环等待、不改 Actions 设置、不 close/reopen PR。未 push（本地 main 领先 origin 32 commit，待用户/维护者决定推送时机）。
