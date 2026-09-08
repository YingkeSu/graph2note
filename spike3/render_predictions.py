"""Render extracted (predicted) diagrams and degradation crops for the report.

Offline: reads whatever is in cache/ (recorded LLM responses), renders each
ok-extracted diagram with both matplotlib and graphviz into plots/pred/, and
crops each sample into plots/degrade/.  Produces result sample images.
"""
from __future__ import annotations

import json
import os

import plot_matplotlib as pm
import plot_graphviz as pg
import extract
from ir_model import Diagram
import prepare_samples

HERE = os.path.dirname(os.path.abspath(__file__))


def render_predictions(model: str = "glm-5.3-flash"):
    reg = prepare_samples.load_registry()
    pred_dir = os.path.join(HERE, "plots", "pred")
    os.makedirs(pred_dir, exist_ok=True)
    out = []
    for name in sorted(reg):
        diag, verdict, meta = extract.extract_result(reg[name]["image"], model)
        if diag is None:
            out.append({"sample": name, "verdict": verdict})
            continue
        for tool, m in (("mpl", pm), ("gv", pg)):
            path = m.render(diag, os.path.join(pred_dir, f"{name}_{tool}.png"))
            out.append({"sample": name, "tool": tool, "path": path,
                        "verdict": verdict})
    return out


if __name__ == "__main__":
    import sys
    model = sys.argv[1] if len(sys.argv) > 1 else "glm-5.3-flash"
    res = render_predictions(model)
    for r in res:
        print(r)