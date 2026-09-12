"""Summarise the U4 before/after graph capture into one comparison JSON.

Offline: reads the two CDP measurement files produced by
``scripts/u4_graph_probe.mjs`` and writes ``graph-interaction-metrics.json``
next to them.  The key readability signal is the *rendered on-screen node size*
and the rendered viewBox per node: the pre-U4 layout stacks all 60 nodes into
one 1000x3348 column, so each node renders at roughly 2px and the labels are
unreadable, while the U4 layout fits them into the viewport at ~60px per node.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def screen_scale(measurement: dict) -> float:
    """Pixels per layout unit as reported by the live SVG CTM."""
    ctm = measurement.get("screenCTM") or {}
    return float(ctm.get("a") or 0.0)


def describe(measurement: dict) -> dict:
    node_count = measurement.get("nodeCount", 0)
    scale = screen_scale(measurement)
    view_box = (measurement.get("viewBox") or "").split()
    return {
        "nodes": node_count,
        "edges": measurement.get("edgeCount"),
        "overlaps": measurement.get("overlaps"),
        "renderedNodePx": measurement.get("minNodeWidth"),
        "viewBox": measurement.get("viewBox"),
        "viewBoxHeight": float(view_box[3]) if len(view_box) == 4 else None,
        "pixelsPerUnit": round(scale, 4),
    }


def main(workdir: str) -> int:
    root = Path(workdir)
    before = load(root / "graph-before.json")
    after = load(root / "graph-after.json")

    before_initial = before.get("initial", {})
    after_initial = after.get("initial", {})
    document_view = (after.get("focus") or {}).get("documentView") or {}
    collapsed = (after.get("cluster") or {}).get("collapsed") or after_initial
    expanded = (after.get("cluster") or {}).get("expanded") or document_view

    report = {
        "captured_with": (
            "headless Chrome CDP probe (scripts/u4_graph_probe.mjs), "
            "http://127.0.0.1:8791/#graph, viewport 1440x1000, "
            "43 seeded documents / 8 topics / 7 tags / 2 collections"
        ),
        "before": describe(before_initial),
        "after": {
            "default_cluster_view": describe(collapsed),
            "expanded_documents": describe(expanded),
            "focus_mode": {
                "faded_nodes": ((after.get("focus") or {}).get("after") or {}).get("faded"),
                "faded_edges": ((after.get("focus") or {}).get("after") or {}).get("fadedEdges"),
                "cleared_faded_nodes": ((after.get("focus") or {}).get("cleared") or {}).get("faded"),
            },
            "zoom": {
                "min": (after.get("zoom") or {}).get("min"),
                "max": (after.get("zoom") or {}).get("max"),
                "fit": (after.get("zoom") or {}).get("fit"),
                "wheel_step": (after.get("zoom") or {}).get("afterWheelIn"),
                "pan_before": (after.get("zoom") or {}).get("panBefore"),
                "pan_after": (after.get("zoom") or {}).get("panAfter"),
            },
            "filters": {
                "edge_source_manual_off": {
                    "hash": (after.get("filterManual") or {}).get("hash"),
                    "sources": (after.get("filterManual") or {}).get("sources"),
                    "nodes": (after.get("filterManual") or {}).get("nodeCount"),
                    "edges": (after.get("filterManual") or {}).get("edgeCount"),
                },
                "single_tag": {
                    "hash": (after.get("filterTag") or {}).get("hash"),
                    "tags": (after.get("filterTag") or {}).get("tags"),
                    "nodes": (after.get("filterTag") or {}).get("nodeCount"),
                    "edges": (after.get("filterTag") or {}).get("edgeCount"),
                },
                "cleared_nodes": (after.get("cleared") or {}).get("nodeCount"),
            },
            "navigation": after.get("navigation"),
        },
        "overlap_pairs": {
            "before_default": before_initial.get("overlaps"),
            "after_default_cluster_view": collapsed.get("overlaps"),
            "after_expanded_documents": document_view.get("overlaps"),
            "after_single_tag_filter": (after.get("filterTag") or {}).get("overlaps"),
        },
    }
    out = root / "graph-interaction-metrics.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(out), "overlap_pairs": report["overlap_pairs"],
                      "before": report["before"], "after_default": report["after"]["default_cluster_view"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/u4-evidence"))
