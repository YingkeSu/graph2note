# Y4 — 真实论文样本回归验证（P1 全合成 fixture）

Status: ready

来源：`/tmp/spw-P1-done-report.md` 风险节 1/3；`/tmp/review-spw-P1-verdict.md` §6-R3；P2/P3 同样只用自建 fixture（`/tmp/review-spw-P2-verdict.md` §2）。属 I 轨遗留（Y 轨）。

## What to build

P1（`tests/test_papers_ingest*.py`）、P2（`tests/test_papers_meta.py`）目前全部使用**合成 PDF / 手写首页文本 fixture**，复杂双栏/跨栏标题、真实排版（页眉页脚、脚注、多语言作者、DOI/arXiv 混排、扫描版）未专项评估。要求收集 3–5 篇真实排版论文做回归 fixture，把「合成样本绿」升级为「真实排版样本有据可查」。

## Acceptance criteria

- [ ] 选取 3–5 篇覆盖不同排版的真实论文（单栏期刊 / 双栏会议 / arXiv 预印本，至少 1 篇复杂双栏），来源与许可记录在 Comments（可用公开 arXiv/CC 论文；仓库内优先存**文本层/首页文本 fixture**，避免大 PDF 入库）。
- [ ] 为每篇登记 fixture：首页文本、全文文本（或 PDF 文本层导出），与期望 title/authors/year/venue/doi/abstract/keywords、References 区切分结果。
- [ ] 断言：P1 文本层直提零 LLM；P2 元数据/参考文献在真实排版上的准确率逐篇记录（允许并记录已知失败，例如 Y5 的摘要并入 authors）；切分失败须为可解释行为（保守合并 + provenance），不静默造条目。
- [ ] 离线：fixture 走文本层路径，零网络零 LLM；扫描版（如纳入）走注入 router 的合成回退，不触网。
- [ ] 记录与合成 fixture 的差异（哪些字段/排版退化），失败 case 转成新 issue 指针（如 Y5）。
- [ ] taxonomy 登记新测试文件；全量 `pytest -p no:warnings` 绿。

## Blocked by

无。建议在 Y5 修复前先补样本（Y5 的复现依赖真实/回流文本）。

## 领地

- 独占：`tests/fixtures/papers/`（新真实样本 fixture）、`tests/test_papers_ingest*.py`、`tests/test_papers_meta*.py`、`tests/taxonomy.py` 登记。
- 禁止：解析算法实现（本次只加 fixture/断言；发现缺陷另开 issue）、大体积二进制 PDF 直接入库（除 license 允许的极小样本）。

## Comments

- P1 done-report 风险 1 原文：「无真实论文样本：fixture 均为合成 PDF，复杂双栏/跨栏标题排版未专项评估。」
- P1 verdict §6-R3（作者已自陈）：合成 fixture、复杂双栏未专项评估；回退聚合论文文档与页面文档可能重复；页号 0-based 需 +1；watchdog 不强制取消线程。后三项分属 X/Y 其他 issue 或既有语义，不在本项。
