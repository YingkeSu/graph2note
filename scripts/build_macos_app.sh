#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$ROOT/build/pyinstaller-config}"

if ! "$PYTHON_BIN" -c 'import PyInstaller' >/dev/null 2>&1; then
  echo "pyinstaller 未安装。请先执行：uv sync --extra web --extra macos" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "此脚本只支持在 macOS 上构建 .app。" >&2
  exit 1
fi

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/macos" \
  "$ROOT/macos/Graph2Note.spec"

APP="$ROOT/dist/Graph2Note.app"
if [[ ! -d "$APP" ]]; then
  echo "构建完成但未找到 $APP" >&2
  exit 1
fi

echo "已生成：$APP"
echo "双击该应用即可启动 Graph2Note。"
