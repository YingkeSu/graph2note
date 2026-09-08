# 扫描 PDF 拆页 + 页级去重 + 缺页预警

Status: in-review

## Parent

[PRD](../PRD.md) P1 增补（扫描 PDF 接入与页级去重）；[SPEC](../SPEC.md) FR-021~023、候选版本实体。

## What to build

把真实扫描工作流（扫描仪出 PDF、重复扫描、漏扫）接入管线。端到端行为：`扫描 PDF 上传 → 按页拆分为图片（页码可追溯）→ 感知哈希近重复检测 → 重复页合并为候选版本 → 有线索时输出缺页预警`。

- PDF 按页拆分：每页产出管线标准图片输入；页码元数据随页携带（拆页顺序），进入 DocumentRecord。
- 页级近重复：pHash/dHash 聚簇；同页多次扫描/上传合并为同一 DocumentRecord 的候选版本（默认最新生效，历史版本留存可查）；阈值可调，误合并可拆分。
- 缺页预警 best-effort：检测页码、日期标题、系列连续性线索，输出疑似缺页警告；无线索时明确不声称完整。
- 首批真实样本：`test-images/` 中 4 个扫描 PDF（文件名含 `_1_`/`_2_` 成对批次，天然含重复扫描场景）。

## Acceptance criteria

- [x] PDF 上传自动拆页进入管线，每页页码可追溯；JPG/PNG 路径行为不变
- [x] 成对重复扫描的页被合并为同一文档的候选版本，文档库无重复条目；默认取最新、历史版本可查
- [x] 近重复阈值可调；提供「拆分误合并」的操作路径（CLI 或 API 层面即可）
- [x] 有页码/日期线索的样本输出缺页预警；无线索样本不声称完整
- [x] 合成图测试：同一页加光照/旋转扰动仍聚为一簇；不同页不误合并
- [x] 4 个真实 PDF 的处理结果与预警输出有记录可查

## Blocked by

- 03-parse-pipeline-cli

## Comments

- 2026-09-08 dispatcher：claimed by graph2note-4（Track B，分支 dev/09-pdf-split-dedup）。**提前启动决策**：Blocked by 03 为集成依赖，但本 issue 的核心（PDF 拆页、pHash 近重复、缺页线索检测）是与解析管线无关的纯函数工作；与 03（graph2note-2 并行进行中）的集成以薄适配层对接，边界：不改动解析管线文件。维护者要求维持 3-4 worker 并行，特此记录。
- 2026-09-08 graph2note-4：交付完成（见 `handoffs/09-pdf-split-dedup.md`）。关键发现：4 个真实扫描 PDF 中并无内容级重复页，naive 去重仅把近空白扫描噪声页误并，已通过 `low_information` 隔离修复（SPEC 非文档页策略）；合成测试覆盖去重/拆分/预警 AC，93 tests 全绿。Status → in-review。
