# 文档时间模型与日期纠偏闭环

Status: merged

## What to build

覆盖 Knowledge Workspace User Stories 1–4。为每个 DocumentRecord 建立可持久化的四时间戳元数据：拍摄时间（capture_time）、手稿日期（document_time）、导入时间（import_time）和修改时间（modified_time）。新文档从图片 EXIF 提取拍摄时间；从 Markdown 内容推断手稿日期，并保存置信度与依据片段；用户可在文档详情中检查、修正日期。元数据通过文档级 API 和 Web 界面读写，与内容版本解耦，手工修正始终优先于自动推断。

端到端路径应覆盖新文档、已有文档的增量回填、推断失败和无 EXIF 的情况；时间字段的有效值按照“手工修正 > 手稿日期 > 拍摄时间 > 导入时间”提供给后续工作台视图。

## Acceptance criteria

- [ ] 新建文档和已有文档都能持久化四个时间字段；无 EXIF 时安全为空，不影响解析或打开文档。
- [ ] 日期推断输出经过 schema 校验，合法结果包含日期、置信度和依据片段；非法、缺失或不可信结果不会覆盖已有元数据。
- [ ] 文档元数据读写 API 与详情 UI 可展示每个时间字段的来源、置信度和依据，并支持用户手工修正。
- [ ] 手工修正不会被重新解析、再次回填或重复推断覆盖；有效时间选择器的优先级有纯函数测试覆盖。
- [ ] EXIF 合成图片、日期推断 golden fixture、持久化重载和 API 契约测试均可离线运行，CI 不调用真实模型。

## Blocked by

None - can start immediately
