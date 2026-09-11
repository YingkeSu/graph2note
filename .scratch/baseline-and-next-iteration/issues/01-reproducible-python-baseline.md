# 恢复可复现的 Python 安装与运行基线

Status: merged

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：从干净环境安装、测试和运行项目；必要的打包与依赖前置整理。

## What to build

让新环境从仓库声明安装后，即可启动 Web、调用 CLI 和 Obsidian 导出，不依赖源码目录或已有 editable 安装意外补齐模块。纳入当前供应商接入改动的离线验证，保留现有运行行为。

## Acceptance criteria

- [ ] 开发、Web、PDF、绘图所需依赖有明确的安装组合，锁文件与声明一致；文档命令在新环境可重复执行。
- [ ] 构建 wheel 后，在没有源码路径和 editable finder 的独立环境中，运行时导入、Web 启动、CLI 和 fixture Vault 导出均成功。
- [ ] 当前 Kimi/DeepSeek 等供应商配置有离线契约覆盖，测试不依赖开发者的真实密钥或默认供应商。
- [ ] 全量源码测试通过；可选依赖造成的跳过逐项列明，不把跳过当作该能力已验收。
- [ ] 证据记录环境、命令、退出码与构建产物；不扩展产品功能。

## Blocked by

None - can start immediately
