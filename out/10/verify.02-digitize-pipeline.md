# 交叉验证分歧报告

- 来源: `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-4/test-images/02-digitize-pipeline.jpg`
- 模型 A: `glm-5.3-flash`　模型 B: `deepseek-v4-flash-vision-exp`
- 验证状态: ✅ 双模型完成

## 汇总

| 类别 | 块数 |
|---|---|
| 双侧一致 (高置信) | 1 |
| 单侧出现 (疑似漏识别) | 10 |
| 不一致 (内容冲突) | 1 |
| 顺序差异 | 否 |

## 双侧一致（高置信）

| # | 块类型 | 位置 | 文本 |
|---|--------|------|------|
| 1 | `heading` | A:2 / B:1 | 笔记/手稿 电子化 (sim=1.0) |

## 单侧出现（疑似漏识别）

| # | 块类型 | 位置 | 文本 |
|---|--------|------|------|
| 1 | `paragraph` | A:- / B:2 | 输入 → 智能解析 → 结构化 → 输出 |
| 2 | `paragraph` | A:1 / B:- | 草图 |
| 3 | `diagram` | A:3 / B:- | 整体流程 \| 输入 \| 解析 \| 格式化 \| 输出 \| f1->f2 \| f2->f3 \| f3->f4 |
| 4 | `paragraph` | A:- / B:4 | 调研： |
| 5 | `paragraph` | A:- / B:5 | 输入：手稿，笔记 → 预置模板（格式：图文 → 排版） |
| 6 | `paragraph` | A:- / B:6 | 解析 |
| 7 | `paragraph` | A:- / B:7 | 解析层：{LLM 直接？ OCR？ 路由} |
| 8 | `paragraph` | A:- / B:8 | 格式化输出：{CSS / markdown（可配置模板）→ 编码 → 渲染} |
| 9 | `diagram` | A:5 / B:- | 抽象 \| 输入层：手稿、笔记等（拍照/扫描）→ 图片/标准文本 \| 解析层：LLM直接解析？OCR？路由！ \| 格式化层：CSS / Markdown（可… |
| 10 | `paragraph` | A:6 / B:- | 设计 |

## 不一致（内容冲突）

| # | 块类型 | 位置 | 文本 |
|---|--------|------|------|
| 1 | `list` | A:4 / B:3 | 输入：手稿、笔记、论文扫描 \| 解析：OCR？排版校验 \| 目标输出格式： \| a. HTML/CSS \| b. Markdown → MVP \| c… (sim=0.7597) |

### 冲突对（A 原文 / B 原文）

- A: `输入：手稿、笔记、论文扫描 | 解析：OCR？排版校验 | 目标输出格式： | a. HTML/CSS | b. Markdown → MVP | c. PDF`
  B: `① 输入：手稿，笔记，论文扫描 | ② 解析：预置 模板 降本 | ③ 结构化 格式： | a. HTML / CSS | b. markdown → MD | c. pdf`
