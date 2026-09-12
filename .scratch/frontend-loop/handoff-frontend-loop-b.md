# Handoff — 前端逐页反馈循环（方向 B「纸感阅读室」）

Status: ready-for-review
Branch: `dev/frontend-loop-b`（基线 `c1313f0`；本地分支，未 push origin，未合并 main）
Scope: `graph2note/webstatic/**` + `scripts/frontend_*.mjs` + `tests/editor_workspace_dom.mjs` + `.scratch/frontend-loop/**`
Range: `c1313f0..5f01255`（14 个提交，每页一个）

## 提交

| 页 | commit | 说明 |
| --- | --- | --- |
| 共享顶栏（BOARD #1） | `d9337d4` | 修复 390px「新解析」溢出；阅读层令牌、焦点环、跳转链接、统一错误面板 |
| 文档库（BOARD #2） | `f2ebb49` | 标题/筛选不再竖排；纸感卡片；空态主操作；加载失败可重试 |
| 时间轴 | `ea1a945` | 日期分组排印；容器内滚动；失败态 |
| 知识图谱 | `84fa43b` | 标签 `labelCharWidth 11→18`、`TARGET_SPAN 980→640`；节点可读性 |
| 数据看板 | `007aefc` | 指标排印与换行；失败态重试 |
| 待整理 | `81a0eab` | 中文命名（Inbox→待整理）；条目层级；失败态 |
| 标签词表 | `859b5bd` | 词条行换行；分组/操作间距；失败态 |
| 问答 | `6f1eeee` | 会话本地滚动；窄窗输入区 sticky；引用排印 |
| LLM 设置 | `2ae06dc` | 表单层级；说明精简（保留「Key 只写不读」） |
| 导出 Vault | `5c0d02e` | 表单纸感；状态换行；窄窗堆叠 |
| 新解析 | `8a2cfd2` | 阅读式标题与格式限制；按钮可达（文件逻辑未改） |
| 修复报告 | `529004d` | 行布局与用户视角文案 |
| 编辑器 + PDF 详情 | `c258fb1` | 三栏滚动、保存状态、原图降级不重试、`aria-label`；DOM shim 补 `getElementById` |
| 跨页回归 | `5f01255` | 巡检脚本 768 宽度 + header 裁切检测 + 原型 opt-in；新增交互脚本；本轮证据 |

## 每页验收汇总

| 页 | 主操作/选中态 | 桌面无裁切 | 窄窗可达 | ≥14/12px | 对比度 | Tab/焦点 | 空/错误态 | 测试 | 无新 pageerror |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 共享顶栏 | ✓ 路由与选中态一致 | ✓ | ✓ 390 无溢出 | ✓ | ✓ | ✓ 焦点环 + 跳转链接 | ✓ | 巡检+交互 | ✓ |
| 文档库 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ `aria-pressed` | ✓ 空态含主操作；失败可重试 | 2 个 mjs/py | ✓ |
| 时间轴 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `timeline_view.mjs` | ✓ |
| 图谱 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ 键盘节点可达 | ✓ | 3 个 mjs/py | ✓ |
| 数据看板 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 巡检 | ✓ |
| 待整理 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `inbox_merge_dom.mjs` | ✓ |
| 标签词表 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `tag_organize_dom.mjs` | ✓ |
| 问答 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ 等待/错误/重试/引用 | `ask_view.mjs` | ✓ |
| LLM 设置 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 巡检 | ✓ |
| 导出 Vault | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 巡检 | ✓ |
| 新解析 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ 失败详情+重试 | 交互 | ✓ |
| 修复报告 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | `test_repair.py` | ✓ |
| 编辑器 + PDF | ✓ 保存状态「已保存」 | ✓ | ✓ 单列可滚 | ✓ | ✓ | ✓ | ✓ 原图降级提示 | `test_webapp_editor_workspace.py` | ✓ |

## 截图索引（`.scratch/frontend-loop/`）

- 修改前 空库：`evidence/{1440,390}-<route>.png` + `evidence/audit.json`
- 修改前 有内容：`before-populated/{1440,390}-<route>.png`
- 修改后 有内容：`final-populated/{390,768,1440}-<route>.png`（11 路由 × 3 宽度）+ `final-populated/audit.json`
- 修改后 空态：`round-2-empty/{1440,390}-<route>.png`
- 失败态与交互：`interactions/error-*.png`、`desktop-editor.png`、`mobile-editor.png`、
  `mobile-pdf-status.png`、`mobile-ask.png`、`mobile-ask-answer.png`、`desktop-graph.png`、
  `interactions/results.json`
- 逐页理由与剩余限制：`.scratch/frontend-loop/progress.md`

## 测试统计

- `pytest`（main venv python，worktree 源码）：**881 passed, 0 failed**（115.6s）。
- `scripts/frontend_audit.mjs`：33 行（11 路由 × 390/768/1440），溢出 0 / 裁切 0 / pageerror 0。
- `scripts/frontend_interactions.mjs`：8/8 PASS，pageerror 0。
- 对比度（WCAG）：ink/bg 13.14、muted/bg 5.83、muted/panel 6.02、accent/bg 5.75、
  accent-dark/accent-soft 6.44、danger/bg 6.00、错误面板 7.32 —— 全部 ≥4.5:1。

复现（本机）：

```sh
GRAPH2NOTE_STORAGE="$PWD/.scratch/frontend-loop/populated-storage" \
  .venv/bin/python -m uvicorn graph2note.webapp:create_app --factory --host 127.0.0.1 --port 8794 &
PLAYWRIGHT_MODULE=<playwright>/index.mjs node scripts/frontend_audit.mjs http://127.0.0.1:8794 /tmp/audit
PLAYWRIGHT_MODULE=<playwright>/index.mjs node scripts/frontend_interactions.mjs http://127.0.0.1:8794 /tmp/interactions
```

## 契约与边界

- 未改 API、存储格式、自动保存契约；`reading.css` 为纯新增层，`style.css` 不变。
- 仅适配既有 DOM/行为，未重构视图数据流。
- CI 零真实 LLM / 零网络；浏览器脚本仅本地运行，不进入 pytest。
- 未改动 `BOARD.md` 阶段状态；未 push origin；未合并 main。

## 剩余限制 / 后续项

1. 失败态只覆盖 7 个数据视图的加载错误；编辑器保存失败与 PDF 上传失败沿用既有 toast/状态行。
2. 视觉质量以截图肉眼复核，自动化只覆盖几何、无 pageerror 与关键交互，不构成「设计优秀」结论。
3. 图谱标签仅验证 bbox 不越界 + 截图，未评估逐字形抗锯齿。
4. 中间轮 `round-1-populated` 未纳入（被 `final-populated` 取代）；如需轮次对比可找回。
5. 本地存在一个更早会话遗留的 uvicorn（127.0.0.1:8795），本会话未使用也未清理。
