# Y4 — 真实论文样本回归验证（P1 全合成 fixture）

Status: ready-for-review

来源：`/tmp/spw-P1-done-report.md` 风险节 1/3；`/tmp/review-spw-P1-verdict.md` §6-R3；P2/P3 同样只用自建 fixture（`/tmp/review-spw-P2-verdict.md` §2）。属 I 轨遗留（Y 轨）。

## What to build

P1（`tests/test_papers_ingest*.py`）、P2（`tests/test_papers_meta.py`）目前全部使用**合成 PDF / 手写首页文本 fixture**，复杂双栏/跨栏标题、真实排版（页眉页脚、脚注、多语言作者、DOI/arXiv 混排、扫描版）未专项评估。要求收集 3–5 篇真实排版论文做回归 fixture，把「合成样本绿」升级为「真实排版样本有据可查」。

## Acceptance criteria

- [x] 选取 3–5 篇覆盖不同排版的真实论文（单栏期刊 / 双栏会议 / arXiv 预印本，至少 1 篇复杂双栏），来源与许可记录在 Comments（可用公开 arXiv/CC 论文；仓库内优先存**文本层/首页文本 fixture**，避免大 PDF 入库）。
- [x] 为每篇登记 fixture：首页文本、全文文本（或 PDF 文本层导出），与期望 title/authors/year/venue/doi/abstract/keywords、References 区切分结果。
- [x] 断言：P1 文本层直提零 LLM；P2 元数据/参考文献在真实排版上的准确率逐篇记录（允许并记录已知失败，例如 Y5 的摘要并入 authors）；切分失败须为可解释行为（保守合并 + provenance），不静默造条目。
- [x] 离线：fixture 走文本层路径，零网络零 LLM；扫描版（如纳入）走注入 router 的合成回退，不触网。
- [x] 记录与合成 fixture 的差异（哪些字段/排版退化），失败 case 转成新 issue 指针（如 Y5）。
- [x] taxonomy 登记新测试文件；全量 `pytest -p no:warnings` 绿。

## Blocked by

无。建议在 Y5 修复前先补样本（Y5 的复现依赖真实/回流文本）。

## 领地

- 独占：`tests/fixtures/papers/`（新真实样本 fixture）、`tests/test_papers_ingest*.py`、`tests/test_papers_meta*.py`、`tests/taxonomy.py` 登记。
- 禁止：解析算法实现（本次只加 fixture/断言；发现缺陷另开 issue）、大体积二进制 PDF 直接入库（除 license 允许的极小样本）。

## Comments

- P1 done-report 风险 1 原文：「无真实论文样本：fixture 均为合成 PDF，复杂双栏/跨栏标题排版未专项评估。」
- P1 verdict §6-R3（作者已自陈）：合成 fixture、复杂双栏未专项评估；回退聚合论文文档与页面文档可能重复；页号 0-based 需 +1；watchdog 不强制取消线程。后三项分属 X/Y 其他 issue 或既有语义，不在本项。

### 交付记录（dev/Y4-real-fixtures）

**实现**：新增真实论文回归 fixture `tests/fixtures/papers/real/`（4 篇，纯文本，不含 PDF）＋ `tests/test_papers_ingest_real.py`（P1）＋ `tests/test_papers_meta_real.py`（P2）；`tests/taxonomy.py` 登记两文件（ingest / workspace）。全量 `pytest -p no:warnings` = **1292 passed**。

**样本与许可**（机读版 `real/manifest.json`，说明 `real/README.md`）：

| key | 论文 | arXiv | 许可 | 页数 | 排版 |
| --- | --- | --- | --- | --- | --- |
| scaling-laws | Scaling Laws for Neural Language Models (OpenAI) | 2001.08361 | arXiv perpetual, non-exclusive 1.0 | 30 | 单栏预印本 |
| constitutional-ai | Constitutional AI (Anthropic) | 2212.08073 | 同上 | 34 | 单栏预印本，51 人作者 |
| deepseek-moe | DeepSeekMoE (DeepSeek) | 2401.06066 | 同上 | 33 | 单栏技术报告，多机构作者 |
| bert | BERT (Google) | 1810.04805 | 同上 | 16 | **双栏会议（NAACL）** |

每篇 fixture：`front.txt`（首页文本）、`lines.jsonl`（全文 PDF 文本层导出，含字号/粗体）、`references.txt`（References 区）、`expected.json`（期望元数据/参考文献切分/已知失败/与合成 fixture 差异）。`_generate.py` 可只读 PDF 复现原始三段文本；`expected.json` 人工维护。

**AC 达成**：
- AC1 ✅ 4 篇覆盖单栏预印本/技术报告/双栏会议；来源+许可+sha256 记入 `manifest.json` 与上表。
- AC2 ✅ 每篇登记首页/全文文本层/references 与期望字段。
- AC3 ✅ `test_real_text_layer_pipeline_makes_zero_llm_calls`：由冻结真实行重建内存 PDF + 注入必抛 router，断言 text-layer 且零调用；P2 逐篇锁定 meta/notes/provenance + `known_failures`，参考文献欠切分断言为保守合并（`merged-continuation`/`merged-incomplete`）且文本不丢（≥90% 归一化覆盖）。
- AC4 ✅ 两文件都有 socket 封锁用例；无扫描样本（17 篇全为文本层原生），扫描回退仍由 `test_papers_ingest.py` 合成用例覆盖。
- AC5 ✅ `expected.json.differences_from_synthetic` + README「已知真实排版失败」表；失败指针见下。
- AC6 ✅ taxonomy 登记；全量绿。

**P2 基线说明**：spawn 时 main（6a45a35）实际 **未含** Y5（BOARD 仍标「待评审」）。为保证 fixture 不锁死 Y5 前行为，本 feature 分支本地合并 `review/Y5-author-split@acdbc79`（并同步 main）作为 P2 基线；仅本地分支操作，未 push。

**发现（未改算法，供另开 issue）**：
1. P1 结构切分把图/表/坐标轴文字（`Layers`、`+ 16`、`1010`、`1024`、`91.2`）当成标题，16–34 页真实论文产生 42–76 个 section → 建议新 issue「真实排版噪声标题抑制」。
2. 首页标题/作者/摘要同块回流时标题吞并 byline（scaling-laws/bert）→ 建议新 issue「P2 标题边界」。
3. 作者列表混入机构/URL/邮箱片段（全部四篇）；双栏页面仍把摘要句并进 authors（bert）→ Y5 家族未覆盖完整，建议新 issue。
4. `doi` 回退 `full_text` 后命中参考文献 DOI（scaling-laws=10.1145/3293883.3295710、deepseek-moe=10.18653/v1/2022）→ 建议新 issue「DOI 只允许首页来源」。
5. 真实无编号/字母键参考文献被整节并成 3–9 个跨页巨条目（`[ACDE12]`、`[Askell et al., 2021]`）→ 建议新 issue「真实参考文献列表切分」。
6. venue/keywords 全缺（arXiv 首页无此二者），属预期非缺陷。
