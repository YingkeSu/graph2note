# macOS 应用

Graph2Note 可以打包为本机使用的 `Graph2Note.app`。应用启动一个只监听
`127.0.0.1` 的本地服务，并在 macOS 原生 WebView 窗口中打开现有界面。

## 构建

在 macOS 上执行：

```bash
uv sync --extra web --extra macos
./scripts/build_macos_app.sh
open dist/Graph2Note.app
```

构建产物位于 `dist/Graph2Note.app`。构建不会收集项目根目录的 `.env`，并会在
产物中发现 `.env` 时拒绝发布。内置与自定义供应商的 API Key 均可在应用内的
「模型设置」输入并保存到本机，保存后不会在界面中回显。旧配置仍可放在：

```text
~/Library/Application Support/Graph2Note/.env
```

应用数据、文档库和模型设置保存在（与 Web/CLI 共用同一套 `graph2note.config` 优先级）：

```text
~/Library/Application Support/Graph2Note/
├── storage/            # 文档库（GRAPH2NOTE_STORAGE 可覆盖）
├── llm-settings.json   # 模型/供应商设置（GRAPH2NOTE_SETTINGS_FILE 可覆盖）
├── .env                # 可选：兼容旧配置，不随应用打包
└── launcher.log        # 启动日志（含 storage=… settings=… 定位行）
```

启动日志 `launcher.log` 会记录 `storage=… settings=…`，用于确认当前文档库位置；
密钥/凭证不写入日志。旧文档库（如 `./.g2n-storage`）不会被搬移或覆盖，设置
`GRAPH2NOTE_STORAGE` 即可继续使用旧目录。

如需停止后台服务，直接关闭应用窗口即可。启动失败日志在上述目录的
`launcher.log`。
