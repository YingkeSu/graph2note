# Z4 — DOI 只允许首页来源

Status: proposed

来源：Y4 真实论文 fixture 发现 #4（`/tmp/spw-Y4-done-report.md` §5；rev-133 verdict §4 独立验证属实：`10.1145/3293883.3295710`、`10.18653/v1/2022` 只出现在 references/正文，front.txt 零命中——`_extract_doi` 的 `full_text` 回退误取参考文献 DOI）。

## What to build

`papers/metadata.py::_extract_doi` 在首页/front 文本未命中时回退全文扫描，会命中参考文献区的他人 DOI 并当作本论文 DOI。DOI 提取应限定首页（或 front 段）来源；首页无 DOI 时如实置空 + notes/provenance 记录，而不是猜。

## Acceptance criteria

- [ ] scaling-laws/deepseek-moe 的 DOI 快照从 wrong 值改为空 + 显式 notes（或正确首页 DOI，若首页实有）。
- [ ] 首页确有 DOI 的合成/真实样本不回退。
- [ ] provenance 记录 DOI 来源范围（front-only）；全量 pytest 绿；mutation 有牙（恢复 full_text 回退须红）。

## Blocked by

无（函数相对独立，但仍在 metadata.py 内——若与 Z2/Z3 同期须协调领地）。

## 领地

- 独占：`graph2note/papers/metadata.py::_extract_doi` 及调用处、相关测试与 real fixture 快照。
- 禁止：作者/标题/摘要函数族（Z2/Z3）。

## Comments

- 小切口项，适合与非同领地项并行派发。
