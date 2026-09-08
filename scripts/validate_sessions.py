#!/usr/bin/env python3
"""按用途对网关直出 session 做一次验证（预算 <= 3 次 live 调用，每用途一次）。

用法：source .env 后 `python scripts/validate_sessions.py`
逐用途探测 parse/eval/verify 会话，打印 reasoning_tokens 与 direct 判定。
输出 JSON 到 reports/session-isolation/scripts/data/validate_sessions.json。
通过 ENV 可覆盖会话或关闭某一用途（--only）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from eval.gateway import (  # noqa: E402
    PURPOSES,
    resolve_session_for,
    validate_session_direct,
)

OUT = Path(__file__).resolve().parents[1] / ".scratch" / "manuscript-compiler-mvp" / "reports" / "session-isolation" / "scripts" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=list(PURPOSES), choices=list(PURPOSES),
                    help="只验证指定用途（默认全部 parse/eval/verify）")
    args = ap.parse_args(argv)

    rows = []
    for purpose in args.only:
        rec = validate_session_direct(purpose)
        rows.append(rec)
        sess = resolve_session_for(purpose)
        flag = "OK" if rec["direct"] else "NOT-DIRECT/CHECK"
        print(f"[{purpose:<6}] session={sess:<28} direct={rec['direct']} "
              f"reasoning={rec['reasoning_tokens']} status={rec['status']} -> {flag}")

    (OUT / "validate_sessions.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT / 'validate_sessions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())