# 上传 PDF 并逐页解析入库

Status: ready-for-agent

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：PDF 上传、拆页、解析、入库与原页查看。

## What to build

用户通过 Web 上传一个 PDF，看到逐页处理状态，成功页进入文档库并可打开三栏校对界面。保留原 PDF 身份、原始页序与页文档/版本的来源映射，能够回看原 PDF 对应页。首个切片即处理多页 PDF，但不承诺跨进程恢复和局部重试。

## Acceptance criteria

- [ ] 小型多页 PDF 从上传到拆页、实际解析和入库全链路可用，不把“待解析”占位当成成功。
- [ ] 存储稳定的原 PDF 标识和页序，结果排序不受异步完成顺序影响，能从页文档打开原 PDF 对应页。
- [ ] 原 PDF 的每个输入页都有可解释状态；空白、重复、成功和失败页可区分，去重后仍保留全部来源映射。
- [ ] 文件类型、大小与页数限制明确；加密、损坏、超限 PDF 有可操作错误；其中一页失败不丢弃成功页。
- [ ] 离线多页 fixture 通过 Web/API/存储/原页查看验证，解析 stub 与真实模型调用隔离；PDF 来源映射重载后仍成立。

## Blocked by

- [03 — clean-baseline-release](03-clean-baseline-release.md)
