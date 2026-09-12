# A1：解析结果自动打标签（识别→标签闭环）

Status: merged
Labels: track-assistant

## What to build

覆盖维护者需求「根据识别结果自动整理标签」。把自动打标从"只有校验骨架"变成闭环：**解析完成 → LLM 推断标签（词表优先）→ 自动挂到文档 → 编辑器可复核 → 存量可批量回填**。

现状盘点（写 issue 时核实）：`tags.py` 已有词表治理（normalize/resolve/ensure/merge/rename）与 `validate_tag_inference` 录制输出校验；`store.add_auto_tags(document_id, raw_tags)` 已能入库；**缺**三块——推断函数本身、解析管线的接线、前端复核体验。

- **推断函数**（新，建议放 tags 或 notes LLM seam 旁）：输入 = 文档 Markdown（截断上限显式）+ 当前词表（规范形式 + 别名）；输出 = JSON `{tags: [...]}`，过 `validate_tag_inference`；prompt 要求「能复用词表就不新增」，新增标签走 `ensure_tag` 自动规范化并入词表。零网络测试用录制 golden（沿 knowledge-workspace issue 02 口径）。
- **管线接线**：单图解析完成、PDF 逐页入库、R1 修复重跑三个入口都触发自动打标；**失败不阻塞解析**（文档照常入库，记录 warning 进 timing/telemetry）。标签带 provenance=auto，与手工标签（manual）可区分。
- **编辑器复核**：auto 标签在文档标签区有视觉标识（如「自动」角标），可一键移除或改为手工保留；文档详情 API 返回每标签的 provenance。
- **存量回填**：CLI `graph2note tags backfill [--dry-run|--yes]`——dry-run 报告待回填文档数与预估调用数，`--yes` 执行；沿 R1 的预算纪律。

## Acceptance criteria

- [ ] 推断函数离线可测：录制 golden fixture（含"复用词表""新增规范化""非法输出被拒"三类），CI 无真实调用。
- [ ] 三个入库入口（单图 / PDF 页 / R1 重跑）完成后文档带 auto 标签；打标失败时解析仍成功且 warning 可查（stub 推断失败路径测试）。
- [ ] auto/manual provenance 在 API 响应与编辑器 UI 中可区分；移除 auto 标签、转为手工保留均持久化。
- [ ] 词表优先语义：fixture 词表已有"机器学习"时，输出"machine learning"应规范化归并而非新建同义标签。
- [ ] `tags backfill` 默认 dry-run，报告数与实际调用数一致（fixture 断言）；`--yes` 执行后存量可补齐，handoff 记录真实库回填结果与预算。
- [ ] 遥测记录每次推断的 token 消费；既有 tags/store 测试全绿。

## Blocked by

None - can start immediately
（领地提示：编辑器标签区 UI 与 U3 有交集，派发时调度协调——A1 以现行 UI 交付，U3 迁布局时保持行为）
