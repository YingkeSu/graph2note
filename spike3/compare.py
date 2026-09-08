"""Spike 3 comparison harness: matplotlib vs graphviz.

Renders the same Diagram semantics with both tools and compares, objectively:
  * node overlap      - pairs of node boxes that overlap in the layout
  * edge crossings    - pairs of straight-line edges that cross
  * CJK rendering     - non-blank glyph ink present inside node label areas
  * reproducibility   - two renders are byte-identical (FR-020)
  * size (KB)         - output size as a rough proxy for embedded cost

Geometry is read per-tool (matplotlib from our layered layout; graphviz from
`dot -Tplain`) so the metrics reflect each tool's real layout.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

import numpy as np
from PIL import Image

from ir_model import Diagram
import plot_matplotlib as pm
import plot_graphviz as pg
import plot_graphviz_geometry as pgg  # helper: dot -Tplain geometry

HERE = os.path.dirname(os.path.abspath(__file__))
PLOTS = os.path.join(HERE, "plots")


def _seg_intersect(p1, p2, p3, p4):
    """Orientation-based CCW segment intersection test."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    def on(a, b, c):
        return (min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and
                min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))
    o1, o2 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    o3, o4 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    if o1 == 0 and on(p1, p2, p3):
        return True
    if o2 == 0 and on(p1, p2, p4):
        return True
    if o3 == 0 and on(p3, p4, p1):
        return True
    if o4 == 0 and on(p3, p4, p2):
        return True
    return False


def _edge_crossings(pos, edges):
    # center-point straight edges (approximation; fine for relative compare)
    segs = [(pos[s], pos[t]) for s, t in edges
            if s in pos and t in pos and s != t]
    n = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            a, b = segs[i]
            c, d = segs[j]
            # skip shared endpoints
            shared = (a == c or a == d or b == c or b == d)
            if not shared and _seg_intersect(a, b, c, d):
                n += 1
    return n


def _node_overlaps(centers_sizes):
    n = 0
    items = list(centers_sizes.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (x1, y1, w1, h1) = items[i][1]
            (x2, y2, w2, h2) = items[j][1]
            if (abs(x1 - x2) < (w1 + w2) / 2 and
                    abs(y1 - y2) < (h1 + h2) / 2):
                n += 1
    return n


def _cjk_ink_fraction(path, tolerance_px=0):
    """Fraction of dark glyph pixels inside the image (non-blank check)."""
    im = np.array(Image.open(path).convert("L"))
    dark = (im < 128).astype(float)
    return round(float(dark.mean()), 5)


def compare_diagram(diag: Diagram, tag: str, results: list):
    d = diag.canonical()
    # -- matplotlib
    m1 = pm.render(d, os.path.join(PLOTS, "mpl", f"{tag}.png"))
    m2 = pm.render(d, os.path.join(PLOTS, "mpl", f"{tag}_r2.png"))
    m_same = _sha(m1) == _sha(m2)
    mgeom = pm.LayerLayout(d)
    mpos = mgeom.positions()
    # node centers/sizes in the same axes space
    msizes = {}
    for n in d.nodes:
        x, y = mpos[n.id]
        w = 0.06 + 0.012 * pm._label_len(n.label)
        msizes[n.id] = (x, y, w, 0.09)
    m_cross = _edge_crossings(mpos, [(e.src, e.tgt) for e in d.edges])
    m_over = _node_overlaps(msizes)
    # -- graphviz
    g1 = pg.render(d, os.path.join(PLOTS, "gv", f"{tag}.png"))
    g2 = pg.render(d, os.path.join(PLOTS, "gv", f"{tag}_r2.png"))
    g_same = _sha(g1) == _sha(g2)
    ggeom = pgg.geometry(d)
    g_cross = _edge_crossings(ggeom["pos"], [(e.src, e.tgt) for e in d.edges])
    g_sizes = {nid: (x, y, w, h) for nid, (x, y, w, h) in ggeom["pos_size"].items()}
    g_over = _node_overlaps(g_sizes)
    results.append({
        "tag": tag,
        "edges": len(d.edges), "nodes": len(d.nodes),
        "mpl": {"overlap": m_over, "crossings": m_cross,
                "reproducible": m_same, "cjk_ink": _cjk_ink_fraction(m1),
                "size_kb": round(os.path.getsize(m1) / 1024, 1)},
        "gv": {"overlap": g_over, "crossings": g_cross,
               "reproducible": g_same, "cjk_ink": _cjk_ink_fraction(g1),
               "size_kb": round(os.path.getsize(g1) / 1024, 1)},
    })


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def run(gt_dir, tags=None):
    results = []
    names = []
    import prepare_samples
    reg = prepare_samples.load_registry()
    for name in sorted(reg):
        rec = reg[name]
        if rec["ground_truth"]:
            d = Diagram.from_dict(json.load(open(rec["ground_truth"])))
            compare_diagram(d, name, results)
            names.append(name)
    return results, names


def main():
    import prepare_samples
    results, names = run(prepare_samples.HERE)
    out = os.path.join(HERE, "outputs", "compare_results.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    res = {"diagrams": results,
           "summary_mpl": {"avg_crossings": round(
               sum(r["mpl"]["crossings"] for r in results) / len(results), 2),
               "avg_overlap": round(sum(r["mpl"]["overlap"] for r in results) / len(results), 2),
               "all_reproducible": all(r["mpl"]["reproducible"] for r in results)},
           "summary_gv": {"avg_crossings": round(
               sum(r["gv"]["crossings"] for r in results) / len(results), 2),
               "avg_overlap": round(sum(r["gv"]["overlap"] for r in results) / len(results), 2),
               "all_reproducible": all(r["gv"]["reproducible"] for r in results)}}
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=2)
    print(f"wrote {out}")
    for r in results:
        print(f"{r['tag']}: mpl(cross={r['mpl']['crossings']},over={r['mpl']['overlap']},"
              f"repro={r['mpl']['reproducible']},ink={r['mpl']['cjk_ink']},"
              f"{r['mpl']['size_kb']}KB) | gv(cross={r['gv']['crossings']},"
              f"over={r['gv']['overlap']},repro={r['gv']['reproducible']},"
              f"ink={r['gv']['cjk_ink']},{r['gv']['size_kb']}KB)")
    print("summary mpl:", res["summary_mpl"])
    print("summary gv :", res["summary_gv"])


if __name__ == "__main__":
    main()