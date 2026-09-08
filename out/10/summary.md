# Issue 10 交叉验证实跑记录

- 评估集样本: ['01-requirements-arch.jpg', '02-digitize-pipeline.jpg']
- 模型 A: glm-5.3-flash / 模型 B: deepseek-v4-flash-vision-exp

| 图像 | 验证 | 一致 | 单侧 | 不一致 | 顺序差 | 重复A/B | 分歧率% |
|---|---|---|---|---|---|---|---|
| 01-requirements-arch.jpg | ✅ | 0 | 14 | 6 | False | 0/0 | 100.0 |
| 02-digitize-pipeline.jpg | ✅ | 1 | 10 | 1 | False | 0/0 | 91.67 |

## 实跑观察（供选型/调优参考）

两模型语义内容大幅一致，但**块粒度/分块结构不同**导致块级分歧率高：

- **01-requirements-arch.jpg**：A（glm）把「Mac↔Mac / Win→Mac / 支持 Apple VNC / Tiger VNC / ssh」压缩为一个 `list` 块；B（deepseek）拆成多个独立 `paragraph`/`list`。同源内容→ 一侧多 `one_side`，0 个 exact-consistent。
- **02-digitize-pipeline.jpg**：结构较接近，1 个 exact-consistent；heading/难点等文本首尾差异→ `conflict`（sim 0.59–0.94）。

结论：**高分歧主要由「list 合并 vs 逐项拆段」的表示差异驱动，而非事实冲突**。后续调优方向：
1. 对齐前对 list/paragraph 做轻量合并规范化（reduce list-split skew）；
2. 分歧率口径区分「结构性（segmentation）」与「内容性（factual）」两种，分别计；
3. 选型时以「事实一致性」为主指标，块级对齐为辅。
