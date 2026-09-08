"""R1/R2/R4/R3 落地后的一次性实时验证脚本（glm 固定 session + 1024 降采样延迟）。

调用数已压缩（当前 2 次 glm）。用法：
    source <repo>/.env
    python validate_gateway.py
结果以 JSON 证据写入 ../validate/。
"""

import json
import os
import sys
from pathlib import Path

# 定位仓库根（向上找 pyproject.toml）
_start = Path(__file__).resolve()
for _p in [*_start.parents]:
    if (_p / "pyproject.toml").exists() and (_p / "eval" / "gateway.py").exists():
        REPO = str(_p)
        break
else:
    raise SystemExit("cannot locate repo root")
sys.path.insert(0, REPO)

from eval import gateway as g  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "validate")
os.makedirs(OUT, exist_ok=True)

IMAGE = os.path.join(REPO, "test-images", "01-requirements-arch.jpg")
MODEL = "glm-5.3-flash"

print(f"image: {IMAGE}")
print(f"sessions(glm): {g.resolve_sessions(MODEL)}")
print(f"first_max_tokens: {g.first_max_tokens()}, timeout: {g.call_timeout()}, downscale: {g.downscale_enabled()}")

runs = []


def run(tag, **kw):
    print(f"\n=== {tag} ===")
    content, meta = g.transcribe_with_policy(IMAGE, MODEL, **kw)
    print(json.dumps(meta, ensure_ascii=False, indent=2)[:2000])
    record = {"tag": tag, "content_len": len(content or ""), "content_head": (content or "")[:80], "meta": meta}
    runs.append(record)
    with open(os.path.join(OUT, f"validate-{tag}.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    print(f"-> saved validate-{tag}.json (content {len(content or '')} chars)")


if __name__ == "__main__":
    # v1: 默认策略（glm 固定 spike-01 + 直出 prompt + 首调 3500 + 1024 降采样）
    run("v1-glm-directed")
    # v2: 复验同样配置（确认 reasoning_tokens 稳定低位、延迟可复现）
    run("v2-glm-repeated")

    summary = {
        "model": MODEL,
        "image": os.path.relpath(IMAGE, REPO),
        "api_sessions_glm": g.resolve_sessions(MODEL),
        "runs": runs,
    }
    with open(os.path.join(OUT, "_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print("\nsaved _summary.json")