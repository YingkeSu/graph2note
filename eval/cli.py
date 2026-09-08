"""评估 harness CLI。

用法（在工作区根目录）：
    python -m eval.cli run --model glm-5.3-flash
    python -m eval.cli run --model deepseek-v4-flash-vision-exp
    python -m eval.cli run --model glm-5.3-flash --nocache
    python -m eval.cli list
"""

from __future__ import annotations

import argparse

from .dataset import CATEGORIES, load_dataset
from .harness import EvalRun, save_predictions, write_report


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eval", description="graph2note 视觉模型质量评估 harness")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="对指定模型跑全量评估集并输出报告")
    run.add_argument("--model", required=True, help="候选模型 id，如 glm-5.3-flash")
    run.add_argument("--nocache", action="store_true", help="忽略缓存，强制重新调用 LLM")
    run.add_argument(
        "--only",
        default=None,
        help="逗号分隔的样本 id 子集（冒烟用）；默认全量",
    )
    run.set_defaults(func=cmd_run)

    lst = sub.add_parser("list", help="列出评估集样本")
    lst.set_defaults(func=cmd_list)

    return p


def cmd_run(args: argparse.Namespace) -> None:
    dataset = load_dataset()
    if args.only:
        allowed = {s.strip() for s in args.only.split(",") if s.strip()}
        dataset = [s for s in dataset if s.id in allowed]

    run = EvalRun(args.model, dataset)
    results = run.run(use_cache=not args.nocache)
    report_path = write_report(run, args.model)
    detail_path = save_predictions(run, args.model)

    print(f"模型 {args.model}: 完成 {len(results)} 个样本")
    for r in results:
        m = r["meta"]
        print(f"  [{r['id']}] cat={r['category']} rate={r['edit_rate']:.4f} "
              f"status={m.get('status','ok')} cached={m.get('cached')}")
    print(f"报告: {report_path}")
    print(f"明细: {detail_path}")


def cmd_list(args: argparse.Namespace) -> None:
    dataset = load_dataset()
    print("评估集清单:")
    for s in dataset:
        proof = "是" if s.gold_proofed else "否"
        print(f"  [{s.id}] {CATEGORIES.get(s.category, s.category)} | gold={s.gold_path} "
              f"| gold人工校对={proof} | {s.notes}")
    print(f"\n类目覆盖: {', '.join(f'{k}={CATEGORIES[k]}' for k in CATEGORIES)}")


def main() -> None:
    args = make_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
