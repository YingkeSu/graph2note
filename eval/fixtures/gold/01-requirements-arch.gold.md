# Agent 编排架构（需求/架构图）

> ⚠️ gold 为 AI 草拟，未经人工校对（HITL 待维护者）。

## 输入层

- 用户画像与需求输入
- 手稿 / 文档图片
- 任务描述

## 解析层

- 智能解析（Recognition Router）
- 链路：图片 → 解析 → 中间表示（IR）

## 格式化输出层

- Markdown 直出
- 模板渲染（CSS / PDF）

## 路由策略

- 视觉 LLM 优先（Route A）
- OCR 路径预留（Route B）
- 按文档类型路由

flow: 输入层 → 解析层（Routing: LLM/OCR） → 格式化输出层
