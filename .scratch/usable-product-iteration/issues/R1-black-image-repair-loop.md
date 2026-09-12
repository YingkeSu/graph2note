# R1：黑图存量检测与重解析闭环

Status: ready-for-agent
Labels: track-repair, priority-high

## What to build

覆盖 usable-product-iteration 草案 §2.2。把 `fix-black-preprocess` handoff 的"建议后续动作"产品化：为存量黑图文档提供**检测 → 报告 → 确认 → 从 `preprocessed_raw.png` 重跑 → 验收**的完整闭环，并实际修复用户库中的存量。

背景：透视 homography bug（修复合并于 `c6f8c52`）导致修复前解析的文档 `preprocessed.png` 为纯黑、下游解析结果为"空白页"。2026-09-12 实测用户库 43 篇中 **22 篇仍为黑图**（另 21 篇正常，其中 3 篇从未触发透视、其余为修复后重解析）。机理与 40 篇原始名单见 `../../baseline-and-next-iteration/handoffs/fix-black-preprocess.md`（修复管线本身已就绪，本 issue 不改 `preprocess.py`）。

三个入口：

1. **CLI**：`graph2note repair scan`（列出黑图文档 + 页数 + 预估 VLM 调用数，dry-run）与 `graph2note repair run [--yes|--doc ID ...]`（执行重跑）。默认 dry-run，`--yes` 才真实调用。
2. **API**：`POST /api/repair/scan` 与 `POST /api/repair/run`（run 必须携带明确的文档 id 列表，不接受全库隐式执行）。
3. **Web**：修复报告入口（可放 Inbox 或维护页，实现自定），展示检测名单与预估成本，用户点击确认后执行并轮询进度（复用 PDF 批任务的 job 模式）。

检测规则（R1 的验收口径）：文档最新版本 `preprocessed.png` 灰度均值 < 10 视为黑图；同时把 Markdown 为"空白页"占位特征的文档列为"疑似"一并报告。`preprocessed_raw.png` 缺失的文档单独标注"需重新上传"，不进自动重跑队列。

重跑路径：从 `preprocessed_raw.png` 走修复后管线（预处理 → 解析 → 新版本入库，同 doc_id 追加 version），**不覆盖旧版本**（保留可回退）。逐篇成功/失败可查，失败可重试。

## Acceptance criteria

- [ ] `repair scan` 对 fixture 文档库（含黑图、正常、缺 raw、疑似空白四类）输出正确分类名单与页数/预估调用数；纯离线（无 LLM 调用）。
- [ ] `repair run` 默认 dry-run；`--yes` 或 Web 确认后执行，重跑产物为新版本（旧版本与 `preprocessed_raw.png` 不被覆盖、不删除），逐篇结果落盘可查。
- [ ] 重跑后的文档 `preprocessed.png` 均值 > 150、墨迹占比 > 0.005（与 handoff 验证口径一致），解析结果非"空白页"。
- [ ] API 与 Web 入口有契约/集成测试（stub 解析器），run 无确认参数时 4xx。
- [ ] 预算报告准确：dry-run 报出的 VLM 调用数与实际执行次数一致（fixture 下断言）。
- [ ] 在用户真实库上执行修复并在 handoff 中记录结果（修复前后黑图计数：22 → 0 或列明例外）。

## Blocked by

None - can start immediately
