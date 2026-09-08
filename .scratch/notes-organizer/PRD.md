# PRD：Notes Organizer — 笔记分类归纳与 Obsidian 呈现（含溯源）

Status: ready-for-agent
Version: v0.1
Created: 2026-09-08
Phase: P1（依赖 manuscript-compiler-mvp 的文档库与去重能力）
Parent feature: manuscript-compiler-mvp（消费其 DocumentRecord）

## Problem Statement

Manuscript Compiler MVP 把每页手稿变成一份份独立 Markdown 文档，但随文档增多它们只是平铺的一堆文件：同一主题散落多页、找不到相关笔记、无法回看当时的原始手稿。用户要的是**知识库**而不是文档堆——需要按内容逻辑分类归纳、可总览、可回溯源的能力。

## Solution

在文档库之上增加**整理层**：对全部 DocumentRecord 的内容语义做分类归纳，导出为 Obsidian vault——

- 每份文档一篇笔记，frontmatter 携带溯源元数据（document_id、来源图片、解析/导出时间、主题），正文首部嵌入原始手稿图片，对照原稿一步到位
- LLM 按内容归纳主题分类 → 文件夹 + 标签；每个主题生成一张 MOC（Map of Content）索引笔记，含该主题全部笔记链接与一句话摘要
- 导出幂等且不破坏用户修改：以 document_id 为锚，重新导出只更新系统生成物；用户编辑/改名过的文件不覆盖（冲突时重命名保留）
- 同源重复解析只导出最新版（复用主管线去重结论）

## User Stories

1. 作为用户，我想把全部已解析文档一键导出为 Obsidian vault，以便在 Obsidian 中浏览与检索笔记
2. 作为用户，我想每份笔记自动带上主题标签并归入分类文件夹，以便同类笔记自动聚拢
3. 作为用户，我想每个主题有一张 MOC 索引笔记（该主题全部笔记链接 + 一句话摘要），以便一眼总览知识结构
4. 作为用户，我想在笔记中直接看到原始手稿图片，以便随时对照识别结果与原稿
5. 作为用户，我想从笔记的溯源信息跳回系统中的原文档（继续编辑或重新解析），以便笔记与源头保持联动
6. 作为用户，我想重新导出时只更新有变化的笔记、且不覆盖我在 Obsidian 里的手工编辑，以便长期维护一个活的 vault
7. 作为用户，我想分类体系由 LLM 根据内容归纳并随新文档演进，以便不必手工维护目录
8. 作为用户，我想对分类不满意时能指定一级分类或整体重跑，以便纠偏
9. 作为学生，我想按课程/科目聚类笔记，以便复习时按科目浏览
10. 作为科研人员，我想按研究主题聚类，以便回顾某个方向的全部草稿
11. 作为用户，我想 vault 内所有链接（笔记 ↔ MOC ↔ 附件）全部有效，以便不点进死链
12. 作为用户，我想导出时同源重复解析只保留最新版，以便 vault 不出现重复笔记

## Implementation Decisions

- **整理层独立于管线**：只读消费 DocumentRecord（IR + Markdown + 附件），不回写主管线；Content ≠ Presentation 原则延续——分类依据内容语义，不依赖版式
- **导出器为纯函数**：`DocumentRecord[] + 分类方案 → vault 文件树`（frontmatter、文件夹、MOC、附件复制），快照测试
- **溯源契约**：frontmatter 必含 `document_id / source_image / parsed_at / exported_at / topics`；正文首部以相对路径嵌入原图；`source_image` 同时指向系统内 DocumentRecord
- **分类归纳**用网关文本模型（无需视觉能力，模型清单见 `docs/llm/opencode-go.md`）对文档集做主题聚类与命名，产出机器可校验的**分类方案**（类别树 + 每文档归属）；方案可人工调整后重导出；小语料（<20 篇）时一级分类不超过 8 个，宜粗不宜细
- **Obsidian 兼容 = 标准 Markdown + wiki links + frontmatter**；不开发插件、不做双向同步
- **增量导出**：document_id 为锚 diff；系统生成文件可被再生成覆盖，用户改名/编辑过的文件不覆盖（冲突文件重命名保留双方）

## Testing Decisions

- **Exporter seam（最高价值）**：fixture 的 DocumentRecord 集合 → 期望 vault 目录树快照（含 frontmatter 字段、MOC 链接、附件落位），并断言全部 wiki link/附件引用可达（无死链）
- **分类 seam**：LLM 分类输出用录制的 golden fixtures，分类方案过 schema 校验后才能进入导出；CI 不 live 调用
- **集成 seam**：从真实（小规模）文档库导出到临时目录，文件系统级断言结构与增量行为（二次导出不覆盖人工修改的文件）
- 好测试标准沿用主 PRD：只测外部行为，不测实现细节

## Out of Scope

- Obsidian 插件开发、双向同步（vault 内编辑回写系统）
- 定时自动整理（手动触发）
- 跨设备同步、发布（Obsidian Publish 等）
- 非中文语料的分类调优

## Further Notes

- 依赖：manuscript-compiler-mvp 的 07（DocumentRecord 持久化）、09（图片去重结论）
- 分类质量随语料增长提升；初期以「可用的一级分类」为目标，不追求精细层级
- 开放问题：分类方案是否需要 UI 预览确认——当前决策为导出时附分类报告，调整后重跑即可，不阻塞
