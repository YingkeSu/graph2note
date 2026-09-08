#!/usr/bin/env python3
"""按用途对网关直出 session 做验证/健康巡检（live 预算 <= 3 次，每用途一次）。

用法（source .env 后）：
  `python scripts/validate_sessions.py`            # 逐用途探测，打印状态，写 JSON
  `python scripts/validate_sessions.py --check`   # 健康巡检：汇总 ok/degraded，任一 degraded 时非零退出
  `python scripts/validate_sessions.py --only parse` # 只查某用途
走批前 `--check` 方便脚本化门控（exit 1 = 有会话退化需处置）。
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
    session_health,
    validate_session_direct,
)

OUT = (Path(__file__).resolve().parents[1] / ".scratch" / "manuscript-compiler-mvp"
       / "reports" / "session-isolation" / "scripts" / "data")
OUT.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=list(PURPOSES), choices=list(PURPOSES),
                    help="只验证指定用途（默认全部 parse/eval/verify）")
    ap.add_argument("--check", action="store_true",
                    help="健康巡检模式：输出 ok/degraded 汇总，任一用途 degraded 时以非零退出码结束（跑批前自检）")
    args = ap.parse_args(argv)

    rows = []
    for purpose in args.only:
        rec = validate_session_direct(purpose)
        rows.append(rec)
        sess = resolve_session_for(purpose)
        semi = "ok" if rec["direct"] else "degraded"
        print(f"[{purpose:<6}] {semi:<9} session={sess:<28} reasoning={rec['reasoning_tokens']} "
              f"status={rec['status']}")

    (OUT / "validate_sessions.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT / 'validate_sessions.json'}")

    if args.check:
        all_direct, bad = session_health(rows)
        if all_direct:
            print("HEALTH: OK")
            return 0
        print(f"HEALTH: DEGRADED ({', '.join(bad)})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())