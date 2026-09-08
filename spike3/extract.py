"""Parse and score VLM extraction results for Spike 3.

Turns each cached raw model answer into a validated Diagram + a verdict
(ok / parse_fail / malformed / no_flow), and scores synthetic samples against
their ground truth (edge-set overlap, node count match).  Purely deterministic
and offline - the pytest suite uses this against recorded fixtures.
"""
from __future__ import annotations

import json
import os
import re

from ir_model import Diagram, Node, Edge

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def try_parse_json(raw: str):
    """Robust JSON extraction from a raw model answer."""
    if not raw or not raw.strip():
        return None
    t = strip_fences(raw)
    try:
        return json.loads(t)
    except Exception:
        pass
    # fall back: find first {...} block
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            return None
    return None


def validate(data) -> tuple[Diagram, str]:
    """Return (diagram, verdict).  verdict in {ok, no_flow, malformed}."""
    if data is None:
        return None, "parse_fail"
    if isinstance(data, dict) and data.get("error"):
        return None, "no_flow"
    if not isinstance(data, dict):
        return None, "malformed"
    nodes, edges = data.get("nodes"), data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return None, "malformed"
    # node ids must be unique, edges must reference existing ids
    ids = {}
    ns = []
    for i, n in enumerate(nodes):
        if not isinstance(n, dict) or "id" not in n:
            return None, "malformed"
        nid = str(n["id"])
        if nid in ids:
            return None, "malformed"
        ids[nid] = nid
        ns.append(Node(id=nid, label=str(n.get("label", ""))))
    es = []
    for e in edges:
        if not isinstance(e, dict):
            return None, "malformed"
        src, tgt = str(e.get("from", "")), str(e.get("to", ""))
        if src not in ids or tgt not in ids:
            return None, "malformed"
        if src == tgt:
            return None, "malformed"  # self-loop likely a glitch, flag it
        es.append(Edge(src=src, tgt=tgt, label=str(e.get("label", ""))))
    if not ns:
        return None, "malformed"
    return Diagram(ns, es).canonical(), "ok"


def extract_result(image: str, model: str) -> tuple[Diagram, str, dict]:
    """Analyze a cached raw answer. Returns (diagram, verdict, meta)."""
    name = os.path.splitext(os.path.basename(image))[0]
    key = f"{name}__{model}.json"
    cpath = os.path.join(CACHE, key)
    if not os.path.exists(cpath):
        return None, "no_cache", {}
    with open(cpath, encoding="utf-8") as fh:
        rec = json.load(fh)
    if not rec.get("ok"):
        return None, "http_error", {"http": rec.get("http")}
    data = try_parse_json(rec.get("raw", ""))
    diag, verdict = validate(data)
    meta = {"raw_len": len(rec.get("raw", "")), "n_nodes": 0, "n_edges": 0}
    if diag:
        meta["n_nodes"] = len(diag.nodes)
        meta["n_edges"] = len(diag.edges)
    return diag, verdict, meta


# ---- scoring against ground truth ----
def _norm(s: str) -> str:
    """Normalize hand/machine punctuation + whitespace for robust matching."""
    s = (s or "").strip()
    s = s.replace("？", "?").replace("！", "!").replace("：", ":")
    s = s.replace("，", ",").replace("；", ";").replace("（", "(").replace("）", ")")
    return "".join(s.split())


def _edge_set(d: Diagram):
    lbl = {n.id: _norm(n.label) for n in d.nodes}
    return {(lbl[e.src], lbl[e.tgt]) for e in d.edges if e.src in lbl and e.tgt in lbl}


def _node_ids(d: Diagram):
    return {n.id for n in d.nodes}


def score_diagram(pred: Diagram, gt: Diagram) -> dict:
    """Structural overlap on the *label* edge skeleton.

    IDs are assigned by the model and differ from ground truth, so the
    structure is compared by node-label pairs (samples carry unique labels);
    labels are normalized (fullwidth/halfwidth punctuation).
    """
    pe, ge = _edge_set(pred), _edge_set(gt)
    inter = pe & ge
    gl = {_norm(n.label) for n in gt.nodes}
    pl = {_norm(n.label) for n in pred.nodes}
    return {
        "n_nodes_pred": len(pred.nodes),
        "n_nodes_gt": len(gt.nodes),
        "n_edges_pred": len(pred.edges),
        "n_edges_gt": len(gt.edges),
        "edges_tp": len(inter),
        "edges_precision": (len(inter) / len(pe)) if pe else 0.0,
        "edges_recall": (len(inter) / len(ge)) if ge else 0.0,
        "node_count_match": len(pred.nodes) == len(gt.nodes),
        "labels_hit": round(len(pl & gl) / len(gl), 2) if gl else 1.0,
    }


def build_report(model) -> dict:
    """Aggregate per-sample verdicts + scores into a report dict (offline)."""
    import prepare_samples
    reg = prepare_samples.load_registry()
    out = []
    for name in sorted(reg):
        info = reg[name]
        diag, verdict, meta = extract_result(info["image"], model)
        score = None
        if diag and info.get("ground_truth"):
            with open(info["ground_truth"], encoding="utf-8") as fh:
                gt = Diagram.from_dict(json.load(fh))
            score = score_diagram(diag, gt)
        out.append({
            "sample": name,
            "real": info["real"],
            "verdict": verdict,
            "meta": meta,
            "score": score,
            "predicted": diag.to_dict() if diag else None,
        })
    return out