# 归档已有工作并形成干净基线

Status: in-review

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：新开发从有明确版本、完整证据的干净工作区开始。

## What to build

在安装与桌面运行验证完成后，核对现有 Kimi、macOS、概念稿、样本及检查产物的归属，形成可追踪的基线提交。临时或敏感文件精确忽略并保留在本机。用整合基线报告说明已完成和仍有证据欠账的范围，不修改或关闭本轮来源文档/父级 issue。

## Acceptance criteria

- [ ] 开始时已有的每项修改均有归属；有价值的工作提交归档，本地专用文件明确忽略，无未知来源改动被丢弃。
- [ ] 密钥、环境配置和编辑器交换文件不进入提交；不为追求 clean 执行破坏性清理或覆盖用户数据。
- [ ] 更新整合看板/运行说明，区分已验收、历史文档滞后和仍需补验事项，不凭测试通过机械勾选所有历史验收项。
- [ ] 最终基线提交上完成规定的测试和安装检查，记录 commit、环境、跳过项、剩余质量欠账；工作区 clean。
- [ ] 如仓库没有 CI checks，记录“无 CI”，本地验收与基线提交完成即停；不循环等待、不改 Actions 设置、不 close/reopen PR。

## Blocked by

- [01 — reproducible-python-baseline](01-reproducible-python-baseline.md)
- [02 — shared-library-macos-app](02-shared-library-macos-app.md)
