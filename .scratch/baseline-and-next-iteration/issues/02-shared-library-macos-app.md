# 统一文档库配置并验收 macOS 应用

Status: merged

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：已有桌面工作收口；Web、CLI 和桌面应用一致访问文档库。

## What to build

建立可解释的共享运行配置，使 Web 创建的文档可被 CLI 导出，桌面应用重启后仍能打开同一文档库。完成现有 macOS 打包与启动工作。已有不同目录的数据不得因默认值调整被移动、覆盖或隐藏；明确切换与沿用旧路径的方法。

## Acceptance criteria

- [ ] Web、CLI、macOS 使用同一套显式配置优先级；各入口能确认当前文档库位置，文档写清默认目录及已有用户如何继续使用旧目录。
- [ ] 在临时目录完成“Web 入库 → CLI 导出 → 桌面打开或同配置重载”验证，无需复制数据，记录身份一致。
- [ ] Graph2Note.app 构建、启动、窗口关闭退出和再次启动通过；用隔离的 Application Support 目录验证文档和模型设置持久化。
- [ ] 配置缺失、路径不可写和启动失败有可定位的错误；日志不泄露凭证。
- [ ] macOS 验收记录与新环境安装文档一致，不操作用户真实文档库来制作测试数据。

## Blocked by

- [01 — reproducible-python-baseline](01-reproducible-python-baseline.md)
