# 交叉验证分歧报告

- 来源: `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-4/test-images/01-requirements-arch.jpg`
- 模型 A: `glm-5.3-flash`　模型 B: `deepseek-v4-flash-vision-exp`
- 验证状态: ✅ 双模型完成

## 汇总

| 类别 | 块数 |
|---|---|
| 双侧一致 (高置信) | 0 |
| 单侧出现 (疑似漏识别) | 14 |
| 不一致 (内容冲突) | 6 |
| 顺序差异 | 否 |

## 双侧一致（高置信）

（无）

## 单侧出现（疑似漏识别）

| # | 块类型 | 位置 | 文本 |
|---|--------|------|------|
| 1 | `paragraph` | A:- / B:2 | Macmini |
| 2 | `diagram` | A:2 / B:- | 局域网通信分层架构草图（Accounts） \| Macbook（常用的文档） \| Windows Laptop \| Mac mini \| linux T… |
| 3 | `list` | A:- / B:4 | Mac ↔ Mac : Screen sharing \| Windows ↔ Mac : Royal TS \| Mac/Windows ↔ Linux : … |
| 4 | `paragraph` | A:- / B:5 | 支持 Apple VNC 协议 |
| 5 | `paragraph` | A:- / B:6 | Tiger VNC 软件 |
| 6 | `paragraph` | A:- / B:7 | Mac/Windows ↔ Linux : ssh -o 密码登录 |
| 7 | `list` | A:4 / B:- | Mac ←→ Mac：screen sharing \| Windows → Mac：RDP TS \| 支持 Apple VNC 协议 \| 或：Tiger … |
| 8 | `paragraph` | A:5 / B:- | Win/mac → Linux：ssh 或 VNC，最轻便 |
| 9 | `paragraph` | A:- / B:12 | Questions : ① 最大吞吐量 → agent 是否兼容 |
| 10 | `paragraph` | A:- / B:13 | prefix / project |
| 11 | `paragraph` | A:- / B:14 | tasks / p1 |
| 12 | `paragraph` | A:- / B:15 | 根目录 / 工作台 |
| 13 | `paragraph` | A:10 / B:- | Questions：① 账号管理/grant？全局技能 |
| 14 | `paragraph` | A:11 / B:- | Programs/016/project/project 假目录 /Tabs /Y 工作目录 |

## 不一致（内容冲突）

| # | 块类型 | 位置 | 文本 |
|---|--------|------|------|
| 1 | `heading` | A:1 / B:1 | 需求： (sim=0.8) |
| 2 | `heading` | A:3 / B:3 | 通信层： (sim=0.6667) |
| 3 | `paragraph` | A:6 / B:8 | 难点：critical patch 优化 (sim=0.8) |
| 4 | `paragraph` | A:7 / B:9 | 问：已有多种 harness，选其固定一种，回答？ (sim=0.5909) |
| 5 | `paragraph` | A:8 / B:10 | 答：三选一种：cost-benefit trade off (sim=0.8627) |
| 6 | `list` | A:9 / B:11 | Logi Graph \| Codex / Session Manage \| Agent Orchestrator (sim=0.9375) |

### 冲突对（A 原文 / B 原文）

- A: `需求：`
  B: `需求`
- A: `通信层：`
  B: `通信`
- A: `难点：critical patch 优化`
  B: `用途 : Critical path 优化`
- A: `问：已有多种 harness，选其固定一种，回答？`
  B: `问题 : 已有多种 harness 构建统一调度`
- A: `答：三选一种：cost-benefit trade off`
  B: `第一种 : cost-benefit trade off`
- A: `Logi Graph | Codex / Session Manage | Agent Orchestrator`
  B: `① Long Graph | ② Codex Session Manage | ③ Agent Orchestrator`
