# 并行开发协议（Parallel Development Protocol）

> 适用：任意 feature 的 `.scratch/<feature>/issues/` 中处于 `ready-for-agent` 的 issue。
> 本文件是**通用协议**：不写死任何具体 issue 分组或波次——分组是调度时依据依赖图动态计算的程序，结果记录在 BOARD（见文末），不记录在本文件。

## 1. 角色

| 角色 | 承担者 | 职责 |
|---|---|---|
| 调度 agent（dispatcher） | 主会话（持有全部项目上下文者） | 分类指派、建 worktree、验收、合并、维护状态。**唯一有权写 main 分支的角色** |
| Worker agent | 被派生的子 agent | 在独立 worktree 内完成所指 issue（或同 track 接力的一串 issue），自测通过后交付 |

## 2. 调度程序（每批次执行）

1. 扫描 `.scratch/*/issues/*.md`，收集 `Status: ready-for-agent` 且未被认领的 issue。
2. 解析每个 issue 的 `Blocked by` 字段，构建依赖图。
3. **分组规则**：存在依赖关系（含传递依赖）的 issue 归入同一 track，由同一 worker 顺序接力（保留上下文）；互不依赖的 issue 分属不同 track，可并行。
4. 并行度 = 当前无阻塞 track 数，上限默认 3 个同时运行的 worker。
5. 依赖未满足的 issue 与 track 本批次不启动（其阻塞项被合并后自动进入下批次候选）。
6. 分类结果、指派与进展写入 BOARD；下一批次回到第 1 步。

## 3. Worktree 与分支

- 调度为每个 track 创建：`git worktree add <主检出目录>/.worktrees/<track-slug> -b dev/<NN>-<slug>`（基于最新 main）。
- 一条 issue 一个分支 `dev/<NN>-<slug>`；track 内接力时，前一条合并后从新 main 重建下一条的分支与 worktree。
- `.worktrees/` 已加入 `.gitignore`。
- Worker 只在自己的 worktree/分支内工作，**永不 checkout main、永不直接向 main 提交**。

## 4. 交接协议（/handoff）

Agent 间一切上下文传递通过交接文档，不依赖对话记忆：

- Worker 完成或中断时调用 `/handoff` 生成交接文档，**保存到 `<主检出目录>/.scratch/<feature>/handoffs/<NN>-<slug>.md`**（覆盖技能默认的 OS temp 目录——跨 worktree 交接需要仓库内稳定路径；其余遵循技能规范：不重复 PRD/issue/commit 已有内容、按路径引用、脱敏、含「suggested skills」节）。
- 交接文档必含：完成了什么、如何运行测试、做出的决策与对 spec 的偏离、未尽事项。
- 接手 agent（同 track 接力或接管半成品）开工前必读：所指 issue 全文 + 对应前序 handoff 文档。
- Dispatcher 派生 worker 的 prompt 必含：issue 文件路径、worktree 绝对路径、分支名、相关 handoff 路径、测试命令、交付要求（代码 + 测试绿 + handoff 文档 + issue 置 `in-review`）。

## 5. Issue 状态机

```
ready-for-agent ──指派──▶ claimed ──worker交付──▶ in-review
    ▲                                           │
    └──────────验收不通过（打回，附意见）◀────────┤
                                                │
                     验收通过、合并入 main ──▶ merged
```

- 状态写在 issue 文件的 `Status:` 行；打回意见追加到该文件 `## Comments` 节；BOARD 同步更新。

## 6. 验收（全自动，无人工环节）

Dispatcher 在 worker 的 worktree 内执行：

1. **全量测试套件绿**（当前项目：`pytest`）。
2. **AC 清单逐项核对**：issue 的每条 Acceptance criterion 须有证据（命令输出、产物路径或测试名）。
3. **代码审查**：调用 `/code-review`（或等价审查流程）。
4. **安全底线**：确认 `.env`、密钥、凭证未出现在任何提交中。

- 通过 → 在主检出目录按**依赖拓扑序** `merge --no-ff` 入 main → push → 删除该 worktree/分支 → 状态置 `merged` → 若合并触及共享契约（schema/接口），通知受影响 track rebase。
- 不过 → issue `## Comments` 写明整改项，状态回 `claimed`，worker 继续修复后重新交付。
- 冲突由 dispatcher 解决；同合约的合并窗口串行化。

## 7. HITL 例外

需要用户参与的事项（供图、gold 校对、spec 级偏离确认）由 dispatcher **汇总后一次性**找用户，worker 不得阻塞等待用户输入；等不到人工输入时先交付可自动验收的部分。

## 8. 技术约定（项目级）

- Python 全栈（3.12+）：管线/渲染器为纯 Python 库；Web 层 FastAPI；图像预处理 Pillow/OpenCV；绘图 matplotlib 或 graphviz（按对应 Spike 结论）；测试 pytest。
- 契约类实现测试先行：先 golden/契约测试，后实现。
- 代码不提交密钥；LLM 调用参数见 `docs/llm/opencode-go.md`。

## 9. BOARD

每个 feature 一张 `.scratch/<feature>/BOARD.md`，列：`issue | track | agent | worktree | branch | status | updated`。由 dispatcher 独占维护（worker 只读）。BOARD 是活状态快照，依赖关系以 issue 文件的 `Blocked by` 为准。
