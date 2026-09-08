# 识别交叉验证引擎：双模型 diff + 重复块检测

Status: in-review

## Status note

issue 10 交叉验证引擎已交付（分支 `dev/10-cross-validation`）。双模型独立解析 → diff → 三类分歧 + 文档内近重复 + 单模型降级「未验证」；实测 4 次 live 调用于两张评估图得到分歧率数据（记 `out/10/`）。详见 [handoff](../handoffs/10-cross-validation.md)。

## Parent

[PRD](../PRD.md) P1 增补（识别交叉验证）；[SPEC](../SPEC.md) FR-024、分歧报告实体。

## What to build

让识别结果可信可见。端到端行为：`图片 → 双模型独立解析（glm-5.3-flash 与 deepseek-v4-flash-vision-exp）→ 两份 IR diff → 分歧报告（CLI 输出 json+md）`。

- 分歧三类标注：双侧一致（高置信）/ 单侧出现（疑似漏识别）/ 不一致（内容冲突）；按 block 聚合呈现。
- 单文档内近重复块检测：同一文档 IR 中语义重复的 block 标出。
- diff 为纯函数：两份合法 IR 进 → 报告出，golden fixtures 测试，CI 不 live 调用。
- 双模型其一失败/超时：降级单模型结果 + 标注「未验证」，不阻塞出稿。
- 报告产出后随文档留存（供 UI 呈现与 notes-organizer 溯源消费）。

## Acceptance criteria

- [x] `verify <image|document>` CLI 产出三类分歧报告（json + 可读 md）
- [x] 一致/单侧/不一致三类在构造的 fixtures 上各有点亮用例
- [x] 单模型失败路径降级为「未验证」标注，端到端不失败
- [x] 文档内重复块检测有正例与负例测试
- [x] 双模型对评估集样本的分歧率数据有记录（供选型与后续调优参考）
- [x] diff 引擎测试全部离线（golden fixtures），CI 无 live 调用

## Blocked by

- 03-parse-pipeline-cli
