# 安装与运行基线

让新环境从仓库声明安装后即可启动 Web、调用 CLI 和 Obsidian 导出，不依赖源码目录或已有 editable 安装补齐模块。

## 前置

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推荐；也可用标准 venv + pip）
- 可选系统二进制（缺失时对应测试整模块跳过，不影响核心链路）：
  - graphviz `dot`：diagram/flow 确定性渲染的**首选**引擎；缺失时 `diagram` extra 内的 matplotlib 回退（纯 Python）。
  - tesseract（含 `chi_sim` 语言包）：OCR Route B；缺失时 `tests/test_ocr.py` 整模块跳过。

## 可选依赖组合（extras）

| extra | 内容 | 用途 |
|---|---|---|
| `dev` | pytest、httpx、reportlab | 测试（FastAPI TestClient 的 httpx）、gold 复核 PDF 合集 |
| `vision` | Pillow、numpy | 预处理 / VLM 输入降采样 |
| `pdf` | pymupdf | 扫描 PDF 拆页（issue 09 ingest） |
| `web` | fastapi、uvicorn、python-multipart | 本地单用户 Web |
| `diagram` | graphviz、matplotlib | diagram/flow 确定性渲染 |
| `macos` | pywebview、pyinstaller、numpy | macOS 桌面打包（`./scripts/build_macos_app.sh`） |
| `all` | 以上全部 | 一键安装开发/测试 + 运行全能力 |

## 一键安装（开发/测试 + 全能力）

```bash
uv sync --all-extras
```

## 测试

```bash
uv run pytest          # 或 .venv/bin/python -m pytest
```

## 运行

```bash
# CLI：Document IR JSON -> Markdown（无需密钥、不触网）
uv run graph2note examples/note.ir.json -o out.md

# CLI：图片 -> 预处理 -> 解析 -> Markdown（需供应商密钥，见 docs/llm/）
uv run graph2note parse <image.jpg> -o out.md

# CLI：文档库 -> Obsidian Vault 增量导出（--storage 可省略，见下方统一配置）
uv run graph2note notes-export --storage <library-dir> -o <vault-dir>

# CLI：显示当前生效的运行配置（文档库/设置位置）
uv run graph2note config

# Web（本地单用户，仅监听 127.0.0.1）
GRAPH2NOTE_STORAGE=<library-dir> uv run uvicorn graph2note.webapp:create_app --factory
```

## 文档库配置（统一）

Web、CLI 与 macOS 桌面应用经 `graph2note.config` 使用**同一套**显式优先级：

| 项 | 优先级 |
|---|---|
| 文档库 storage | 显式参数（CLI `--storage` / `create_app(storage_dir=)`） > `GRAPH2NOTE_STORAGE` > `<support>/storage` |
| LLM 设置 settings | `GRAPH2NOTE_SETTINGS_FILE` > `<storage>/llm-settings.json` |
| 应用数据根 support | `GRAPH2NOTE_APP_SUPPORT` > `~/Library/Application Support/Graph2Note`（非 macOS 为 `~/.local/share/Graph2Note`） |

各入口确认当前位置：Web `GET /api/config`；CLI `graph2note config`；macOS 应用写 `launcher.log` 的 `storage=… settings=…` 行。

**旧目录迁移**：此前 Web 默认 `./.g2n-storage`、`notes-export` 默认 `./storage`。统一后默认目录不变动、不搬移、不覆盖任何旧数据——沿用旧目录只需 `export GRAPH2NOTE_STORAGE=$(pwd)/.g2n-storage`（或 CLI 显式 `--storage`）。

## 构建 wheel 并做独立环境验证

```bash
uv build --wheel --out-dir dist
uv venv /tmp/graph2note-iso
uv pip install --python /tmp/graph2note-iso/bin/python 'dist/graph2note-0.1.0-py3-none-any.whl[all]'
# 在仓库目录之外运行验证（无源码路径、无 editable finder）：
/tmp/graph2note-iso/bin/python -m graph2note.cli examples/note.ir.json --stdout
```

## 供应商配置（Kimi / DeepSeek）

网关与密钥经环境变量或 `.env`（gitignored）读取；密钥**不进入**提交与快照。`GRAPH2NOTE_GATEWAY` 选择供应商（`opencode` / `deepseek` / `kimi`）。离线契约测试见 `tests/test_gateway_select.py`、`tests/test_llm_settings.py`、`tests/test_config.py`。
