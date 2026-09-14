# P1 — 论文 PDF 导入管线（文本层直提 + 章节结构 + 扫描回退）

Status: ready

来源：维护者 2026-09-14 指令「增加论文导入模块，针对论文识别读取做全线优化」；共享契约 [SPEC.md §2](../SPEC.md)。

## What to build

新包 `graph2note/papers/` 的导入管线：用户通过 Web 上传论文 PDF，系统**优先走文本层直提**（born-digital 论文不经过截图→VLM 的失真路径），确定性切分出章节结构（`PaperSection` 树/列表）+ 全文纯文本 + 页映射，入库为 `doc_kind: "paper"` 的真实库文档；无文本层的扫描版论文**回退**现有 VLM 逐页解析路径并在 provenance 标注 `source: "vlm"`。为 P2 的元数据/参考文献识别预留槽位（meta/references 字段可先为空）。

## Acceptance criteria

- [ ] 带文本层的论文 PDF fixture（自建小型合成 PDF 或截取的真实论文页）上传后，正文内容来自**文本层直提**而非 VLM，离线测试断言抽取文本与 fixture 文本层一致，且全程零 LLM 调用。
- [ ] 章节结构确定性切分：fixture 的「1 Introduction / 2 Method / 2.1 … / References」被识别为 `PaperSection(level, title, text, page_start/end)` 列表；切分逻辑对字号/编号启发式可测、可回放。
- [ ] 无文本层（扫描版）PDF 自动判定并回退 VLM 逐页路径，provenance `source: "vlm"`；判定逻辑本身离线确定性（文本层字符密度阈值等），回退路径走可注入 `router_factory`，CI 不触网。
- [ ] 入库文档带 `doc_kind: "paper"` 与论文 provenance（source_pdf/pdf_id/page 映射沿用 issue 08/09 机制）；`store.save_document` 只追加式扩展，既有调用行为不变。
- [ ] Web/API：`POST /api/papers/import`（或等价命名）上传 + 状态查询 + 结果查询；`webapp.py` 只追加 `/api/papers/*` 段；加密/损坏/超限 PDF 有可操作错误；沿用 `pdflib.py` 的大小/页数限制与 job 持久化/恢复/重试语义（可复用不复制）。
- [ ] 页映射保留：每个 section 可回溯到原 PDF 页码区间，原页查看沿用 `/source-page` 机制。
- [ ] 全部测试离线；新增测试文件独立命名（如 `tests/test_papers_ingest.py`）；全量 pytest 绿。

## Blocked by

无（与 P2/P3 通过 SPEC §2 契约并行；P2/P3 不 import 本 issue 未合并代码）。

## 领地

- 独占：新包 `graph2note/papers/`（`pipeline.py`、`textlayer.py`、`structure.py`、`model.py` 等自建文件）、`tests/test_papers_ingest*.py`、`webstatic/js/views/upload.js`（论文上传入口，追加式）。
- 只追加：`graph2note/webapp.py`（`/api/papers/*` 段）、`graph2note/store.py`（确需时只追加新方法/新可选字段）。
- 禁止：`ir.py`、`diagram*`、`digest.py`、`dashboard.js`、`index.html`、`router.js`（他人领地）。

## Comments

（待 worker 填写交付记录）
