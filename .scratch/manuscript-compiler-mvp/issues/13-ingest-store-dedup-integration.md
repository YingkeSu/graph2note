# Ingest↔Store 集成：同页多次扫描合并为 DocumentRecord 候选版本

Status: claimed

## Parent

[PRD](../PRD.md) User Story 31 + 「扫描 PDF 接入与页级去重（P1 增补）」决策（同页多次扫描/拍摄合并为同一 DocumentRecord 的候选版本，默认取最新、其余版本留存可查）。证据：issue 07 交付时明确遗留（"full FR-022 pHash ingest merge deferred to issue 09 机制"），09 的 pHash 聚类与 07 的 FileDocumentStore 均已合并但尚未打通。

## What to build

把 09 的页级近重复检测接入 07 的文档库写入路径。端到端行为：`同一页的第二次扫描/拍摄上传 → pHash 判定同源 → 并入既有 DocumentRecord 成为候选版本（默认取最新，历史版本留存可查）；不同页不误并；误并可拆分`。

- 上传/ingest 路径：对新页图计算 pHash（复用 `graph2note/ingest/` 的 hash/cluster），与库内既有页图比对；命中近重复 → 并入目标 DocumentRecord 作为新候选版本（含来源图与解析结果），不新建文档。
- 版本呈现：文档详情可见候选版本列表（来源、时间、当前生效版）；默认取最新，可查看历史版本（最小 UI 呈现即可，web 已有版本徽章可扩展）。
- 阈值可调 + 误合并可拆分：复用 09 的 recluster 可逆机制；Web 提示「检测到重复页，已并入文档 X」。
- 与 PDF 批量 ingest（09 CLI）打通：批量导入时同页去重后逐页建档。

## Acceptance criteria

- [ ] 同页不同光照/角度的两次上传端到端并入同一 DocumentRecord（合成样本测试）
- [ ] 不同页不误并（负例测试）；误并后可拆分（recluster 路径测试）
- [ ] 候选版本留存可查，默认最新生效
- [ ] PDF 批量 ingest 去重后逐页建档的集成测试
- [ ] Web 端重复并入提示与版本查看最小呈现
- [ ] 全部离线测试绿，无网络依赖

## Blocked by

None（09、07 均已合并；机制齐备，纯集成）
