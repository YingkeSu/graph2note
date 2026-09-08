# Diagram 重建：nodes/edges → 确定性绘图 → 附件嵌入 + 裁原图降级

Status: claimed

## Parent

[PRD](../PRD.md)（流程图重建进 MVP、附件机制）；[SPEC](../SPEC.md) FR-009、FR-020、Attachment 实体。

## What to build

把 issue 04 的可行结论产品化，接入渲染层。端到端行为：`Document IR 中的 diagram/flow block（nodes/edges 语义）→ 确定性绘图 → 图片落盘为文档附件 → Markdown 以相对路径图片语法嵌入`。

- 绘图工具链按 issue 04 结论选型；同一 diagram 语义产出逐字节/逐像素一致的结果。
- 解析层无法提取结构语义时（VLM 返回的 diagram block 缺 nodes/edges 或标记降级），从预处理后原图按 bbox 裁剪嵌入，解析不失败、不产生乱码。
- 附件随文档组织（assets 目录），导出时保证 `.md` 引用的附件全部随附；引用缺失在输出时标出。

## Acceptance criteria

- [ ] 含 diagram block 的 IR 渲染出 `.md` + 图片附件，节点标签与连线方向可读
- [ ] 同一 diagram 语义重复渲染输出一致（确定性测试）
- [ ] 语义缺失的样本走裁剪原图降级路径，端到端不失败
- [ ] 中文节点标签渲染正常（无乱码/方框）
- [ ] 附件完整性检查：`.md` 中每个图片引用都有对应文件存在

## Blocked by

- 02-ir-schema-markdown-renderer（渲染器与附件接口）
- 04-spike3-diagram-rebuild（绘图工具链选型结论）
