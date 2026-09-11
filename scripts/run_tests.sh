#!/bin/zsh
# 模块级测试运行（issue 12）。
#
# 用法：
#   scripts/run_tests.sh webapp                    # 单模块
#   scripts/run_tests.sh webapp notes              # 多模块（or 组合）
#   scripts/run_tests.sh --unit                    # 全部单元测试
#   scripts/run_tests.sh --integration             # 全部集成测试
#   scripts/run_tests.sh --fast                    # 排除 slow
#   scripts/run_tests.sh --all                     # 全量（大版本合并前）
#
# 模块（marker）名与「改了模块 X 应跑哪些测试」映射表见 docs/testing.md。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -eq 0 ]; then
  echo "用法: scripts/run_tests.sh <module> [module ...] | --unit | --integration | --fast | --all" >&2
  echo "模块: ir render preprocess pipeline ingest verify webapp notes workspace visualqa eval diagrams config store cli" >&2
  exit 2
fi

case "$1" in
  --all)
    uv run pytest
    ;;
  --unit)
    uv run pytest -m unit
    ;;
  --integration)
    uv run pytest -m integration
    ;;
  --fast)
    uv run pytest -m "not slow"
    ;;
  *)
    expr=""
    for m in "$@"; do
      expr="${expr}${expr:+ or }${m}"
    done
    uv run pytest -m "$expr"
    ;;
esac
