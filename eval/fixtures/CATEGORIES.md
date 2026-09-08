# 评估集类目与扩充约定

评估集目录约定：图片按类目分类，样本唯一 id 标识；每样本一条 metadata 记录。

## 六类目

| key | 中文 | 说明 |
|---|---|---|
| `handwriting` | 手写笔记 | 手写课堂/会议/草稿笔记 |
| `print` | 印刷扫描 | 印刷体论文/讲义扫描 |
| `formula` | 数学公式 | 含 LaTeX 公式的页 |
| `mixed` | 中英混排 | 中英文混合排版的页 |
| `flowchart` | 流程图/架构图 | 流程/架构/箭头图 |
| `strikethrough` | 涂改/删除线 | 含删除线/涂抹的样本（语义化删除专项） |

## 文件布局

```
eval/fixtures/
  metadata.json              # 样本清单（id、category、image、gold、gold_proofed、notes、deletion_note）
  gold/<id>.gold.md          # gold Markdown（AI 草拟 + 人工校对）
  data/<id>.<ext>            # （可选）图片副本；当前图片直接复用仓库根 test-images/，metadata 用相对路径引用
```

gold 未人工校对时 `gold_proofed=false`，报告会自动标注「未经人工校对」。

## 怎么扩充评估集（给维护者 / 后续 worker）

1. 把新图片放入仓库（建议 `test-images/` 或 `eval/fixtures/data/`），记下路径。
2. 在同级 `gold/` 下写 `<new-id>.gold.md`（AI 辅助草拟时可临时标 gold_proofed=false）。
3. 在 `metadata.json` 的 `samples` 增加一条：`id`、`category`（必须是上面六类之一）、
   `image`（相对仓库根路径）、`gold`（相对仓库根路径）、`gold_proofed`、`notes`、`deletion_note`（涂改类目专用）。
4. 跑 `python -m eval.cli list` 确认样本入列，再 `python -m eval.cli run --model <model>`。
5. 维持样本加量时注意配额（同图同模型结果已在 `eval/cache/` 缓存，不重复调用）。
