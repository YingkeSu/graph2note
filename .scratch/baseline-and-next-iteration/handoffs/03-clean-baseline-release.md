# Handoff — issue 03：归档已有工作并形成干净基线

Branch: `ao/graph2note-10/03-clean-baseline-release`
Worktree: `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-10`（基于 main `32fe1d3`）

## 完成了什么

归档实体工作在前置合并任务已完成（归档 commit 列表见 §AC1），本 issue 补足**证据整合与状态收尾**：

- **`BASELINE.md`**（新增）：整合基线报告，逐条覆盖 5 条 AC——每项改动的归属 commit、敏感文件忽略、已验收/历史滞后/待补验三类状态、测试+安装检查记录、无 CI 声明。
- **`BOARD.md`**：issue 03 状态 → in-review（指向 BASELINE.md）。
- **`issues/03-clean-baseline-release.md`**：Status → in-review。
- 未修改/未关闭来源文档 `ASSESSMENT.md`、`ISSUE-DRAFT.md` 与父级 issue。

## 如何运行测试

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-10
uv sync --all-extras
uv run pytest            # 424 passed, 0 failed, 0 skipped（基准 32fe1d3 上）
```

## 验收证据（逐条 AC）

- **AC1 每项修改有归属、无未知改动丢弃**：见 `BASELINE.md` §1 归属表（macOS `16946be`、Kimi `25117d7`、PRD `ec0192b`、baseline docs `92c3e8a`、样本 `e413dfb`）+ issue 01–06 merge commit 表。
- **AC2 密钥/交换文件不入提交、无破坏性清理**：`git ls-files` 无 `.env*`；`.env.sw?` 精确忽略；旧库/用户数据未移动覆盖（见 issue 02 AC5）。
- **AC3 看板/运行说明区分三类状态、不机械勾选**：`BASELINE.md` §3（已验收 01–06 / 历史文档滞后 manuscript-compiler-mvp+notes-organizer / 待补验 EditRate、预处理黑图 bug、印刷样本、macOS UI 点击）。
- **AC4 最终基线提交上的测试+安装检查记录 + 工作区 clean**：`32fe1d3` 上 `424 passed`；wheel 构建退出码 0 + 独立 venv `whl[all]` 安装 + 隔离目录「导入→Web→CLI」三步 PASS；环境 Python 3.13.13/uv 0.11.17/pytest 9.1.1/arm64；跳过项 0（缺失跳过点记录在 docs/setup.md）。
- **AC5 无 CI 即停**：`BASELINE.md` §5 记录「仓库无 CI checks」，本地验收完成即停，不 push、不改 Actions。

## 决策与对 spec 的偏离

- **归档 commit 在前置合并任务完成**：本 issue 不再重复提交实体改动，只做证据报告 + 看板/状态收尾（避免重复归档）。
- **新增 `BASELINE.md` 而非改写 `ASSESSMENT.md`**：spec 要求「不修改或关闭本轮来源文档/父级 issue」，故整合证据另立新文件并互链。
- **未 push**：main 领先 origin 32 commit，推送时机留给维护者。

## 未尽事项 / 给接力者

- 基线提交 `32fe1d3` 后，`manuscript-compiler-mvp`/`notes-organizer` 的历史 BOARD/AC 勾选仍滞后，未在本轮机械勾选（属历史文档，非本轮 scope）。
- 待补验质量欠账见 `BASELINE.md` §3（尤其预处理 perspective 黑图 bug 有独立 handoff `fix-black-preprocess.md`，建议尽早立项修复）。
- issue 07（graph2note-11，验收打回修正中）、08（graph2note-12，rebase 中）后续由调度继续。

## Suggested skills

- 本 issue 为证据梳理 + 文档更新，无 UI/无诊断需求；`impeccable`/`prototype`/`diagnose` 均不适用。
