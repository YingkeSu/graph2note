# Diagram 重建：nodes/edges → 确定性绘图 → 附件嵌入 + 裁原图降级

Status: merged

## Parent

[PRD](../PRD.md)（流程图重建进 MVP、附件机制）；[SPEC](../SPEC.md) FR-009、FR-020、Attachment 实体。

## What to build

把 issue 04 的可行结论产品化，接入渲染层。端到端行为：`Document IR 中的 diagram/flow block（nodes/edges 语义）→ 确定性绘图 → 图片落盘为文档附件 → Markdown 以相对路径图片语法嵌入`。

- 绘图工具链按 issue 04 结论选型；同一 diagram 语义产出逐字节/逐像素一致的结果。
- 解析层无法提取结构语义时（VLM 返回的 diagram block 缺 nodes/edges 或标记降级），从预处理后原图按 bbox 裁剪嵌入，解析不失败、不产生乱码。
- 附件随文档组织（assets 目录），导出时保证 `.md` 引用的附件全部随附；引用缺失在输出时标出。

## Acceptance criteria

- [x] 含 diagram block 的 IR 渲染出 `.md` + 图片附件，节点标签与连线方向可读
- [x] 同一 diagram 语义重复渲染输出一致（确定性测试）
- [x] 语义缺失的样本走裁剪原图降级路径，端到端不失败
- [x] 中文节点标签渲染正常（无乱码/方框）
- [x] 附件完整性检查：`.md` 中每个图片引用都有对应文件存在

## Blocked by

- 02-ir-schema-markdown-renderer（渲染器与附件接口）
- 04-spike3-diagram-rebuild（绘图工具链选型结论）

## AC 状态（2026-09-08 Track B 完成）

- [x] 含 diagram/flow block 的 IR 渲染出 `.md` + 图片附件：`graph2note/diagrams/` 实现真实绘图，节点标签与连线方向可读（CLI + `examples/diagram-demo.ir.json` 演示验证）。
- [x] 同一语义重复渲染输出一致：graphviz 与 matplotlib 两引擎均逐字节一致（`tests/test_diagrams.py` 确定性用例）。
- [x] 语义缺失走裁剪原图降级：`diagram/flow.source`（向后兼容可选字段）→ `degrade.crop_image`；无源图时输出确定性空白占位，端到端不失败。
- [x] 中文节点标签渲染正常：graphviz 经 fontconfig → Arial Unicode MS，matplotlib CJK 字体探测；无乱码/方框（示例样张验证）。
- [x] 附件完整性：`missing_attachments(md, assets_dir)` 校验每个图片引用有对应文件，缺失时明确报出。

## 备注 / Handoff

实现与接口决策见 `handoffs/05-diagram-render-attachments.md`。测试 `tests/` 54 项全绿、无网络；graphviz 用例在包/二进制缺失时干净 SKIP。真实 LLM 未调用（用构造 IR 与缓存语义）。
