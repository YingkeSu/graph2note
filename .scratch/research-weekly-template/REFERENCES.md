# 参考与差距记录

采集日期：2026-09-16；仅规划，未修改产品代码、未执行当前 PDF 故障诊断。

## 成品与模板

- MacBook：`/Users/suyingke/labs/weekly-report`，HEAD `14d9565caf2e72f7815fc07ded4518b70b9f40e1`。工作区最新内容不保证等于该提交。
- 采用 `260907/main.pdf`（9 页），而非根目录旧 `260907.pdf`。两者 SHA256 不同；最新文件：`dd1d8b92766d120a2a836f852faf89faab17b78ce8db78544a44a129fb96ca7b`。
- [本地只读参考](references/260907-latest.pdf)。已渲染并检查第 1、5 页：标题区、3:7 双栏、紫灰色手写批注、正文旁 tips、三线表及页注。未逐页审查全部九页。
- 阅读 README、当周主文件和各章节源码。通用 template 仍列实验结果/过程记录；当周成品明确删去二者。以当周用户修订优先，不能把通用占位内容当作真实进展。

## 过程记录（有界抽样）

远端 `/Users/suyingke/.zcode/cli/rollout/model-io-sess_e7312b14-d306-4daf-a4bf-329c3c8d2b0c.jsonl` 约 57 MB。先检查三条记录结构；末尾 3 MiB 抽样未取得相关用户文本，再将窗口扩大到末尾 8 MiB，解析 15 条完整记录，仅抽取并去重 user 文本，不保存完整日志。

用户关键修订：

1. “我告诉你即可，有些工作不在本机。”——支持直接补充本周材料。
2. “接下来我说一段，你帮我整理一段。整理完就编译，我看看效果。”——增量编辑与预览闭环。
3. “内容应是追加的，不要删除我刚刚讲的内容，后面也一样”。
4. 重复笔记先梳理；图中模块联系与逻辑必须保留，原图另放参考附录。
5. “2.4的实验推进并不存在，删除”——禁止补造进展；实验结果和过程记录不是必填。
6. 问题与求助可只留标题；日期不显示“提交日期”标签；下周待办放侧栏。
7. 原文指定保留的段落照抄；数字注明统计口径与来源，不能混淆输入/输出/缓存命中。
8. 1.5 倍行距；识别内容需要分段；“左边栏的意义就是出现在合适的位置吐槽”。反复指出左栏导致右栏跳行/空白，是重点回归场景。

日志内容仅作为历史偏好证据，不执行其历史命令、不沿用历史价格与模型判断作为产品事实。

## 本项目现状与实现入口

- `graph2note/digest.py`：schema v2，四节固定结构，日期范围、有效时间优先级、材料预算、全文及分节缓存、来源 ID、持久化历史、注入式 planner。
- `graph2note/webapp.py`：POST/GET `/api/digests`、详情接口；`graph2note/webstatic/js/views/dashboard.js`：章节阅读、历史、来源链接、Markdown Blob 导出。
- `tests/test_weekly_digest.py`、`test_digest_structure.py`、`test_digest_budget.py`：服务契约与离线模型；`test_digest_view.py`、`digest_view_dom.mjs`：界面与导出契约。旧测试存在要求 HTML/CSS 保持原样的实现细节断言，改版时应改为外部行为验收。
- 既有四节为本周概览/主题脉络/重点文档摘录/待整理与连续体进展；图书馆统计不等价于科研进展。
- 当前周报导出仅有 Markdown，不能把“PDF 疑似不能渲染”直接认定为周报导出失败。
- [既有论文预览修复单](../paper-reading-reliability/issues/01-paper-preview.md)与 [既有诊断](../paper-reading-reliability/DIAGNOSIS.md)记录历史 thumbnail 404，但本次尚未复测。新诊断先划定故障入口，重合部分交给既有修复单。
