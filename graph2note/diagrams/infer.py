"""Deterministic diagram/flow inference from Markdown (issue 15).

The two-stage Route A pipeline's stage-1 VLM already *transcribes* diagrams
into ``A → B`` relation lines (see ``vlm.MARKDOWN_USER_PROMPT``: "提取节点与
箭头关系，用 Markdown 列表或简短文字描述连线方向（如 '节点A → 节点B'）").  This
module turns those lines into structured ``flow``/``diagram`` blocks with a
pure, deterministic, offline parser — no extra LLM call.

Detection (issue 15 task §检出, decision documented in the issue):

* a page "contains a diagram" iff its Markdown shows arrow/relation patterns
  (``→``, ``-->``, ``->``, ``=>``, bidirectional ``↔``/``<->``) or a diagram
  keyword (``流程图`` / ``架构图`` / ``flow:`` / ``diagram``).  We choose this
  text-structural detector over a live VLM page-classification call — the
  stage-1 VLM already transcribes every diagram page into just such lines, so
  an extra per-page classification call would only add live cost/budget and an
  offline-test burden without adding signal.

Backward compatibility: ``_markdown_to_ir`` keeps every non-relation line's
existing block mapping; only contiguous relation lines that would otherwise be
plain paragraphs are lifted into a ``flow`` block (structured) or a caption-only
``diagram`` block (unparseable but relation-like -> original text preserved).
"""

from __future__ import annotations

import re

# Relation tokens, longest first so multichar symbols match before single one.
_RELATION_TOKENS = ("-->", "<->", "←→", "←->", "->", "=>", "↔", "←", "→")


def _first_relation_op(line: str) -> int | None:
    """Index of the first relation operator in ``line`` (longest match first)."""
    best = None
    for tok in _RELATION_TOKENS:
        j = line.find(tok)
        if j != -1 and (best is None or j < best):
            best = j
    return best


def is_relation_line(line: str) -> bool:
    """True when a line encodes a node/arrow/node (or bare arrow) relation."""
    s = (line or "").strip()
    if not s:
        return False
    return _first_relation_op(s) is not None


def _clean_token(text: str) -> str:
    text = text.strip().strip("　 \t")
    # drop a leading bullet/quote artifact if the line was shifted
    text = re.sub(r"^[-*+>\s]+", "", text).strip()
    return text


def parse_relation_line(line: str) -> tuple[str, str, str] | None:
    """Parse ``A → B`` (or ``-->``/``->``/``=>``/``↔``) into (src, tgt, label).

    An optional edge label is taken from ``:``/``：`` after the target
    (``A → B：说明``).  Bidirectional ``A ↔ B`` yields two directed edges in
    the caller.  Returns None when the line has no clear two-sided relation
    (e.g. a bare arrow line with an empty side).
    """
    s = line.strip()
    idx = _first_relation_op(s)
    if idx is None:
        return None
    matched = None
    for t in _RELATION_TOKENS:
        if s.startswith(t, idx):
            matched = t
            break
    if matched is None:
        return None
    left = _clean_token(s[:idx])
    right = _clean_token(s[idx + len(matched):])
    if not left or not right:
        return None
    # edge label after target: "A → B：说明" / "A → B: label"
    tgt, label = _split_label(right)
    if not tgt:
        return None
    return (left, tgt, label, matched)


def _split_label(right: str) -> tuple[str, str]:
    """Split ``B：说明`` -> (B, 说明); ``B: x`` -> (B, x); else (right, '')."""
    for sep in ("：", ":"):
        if sep in right:
            head, _, rest = right.partition(sep)
            head = head.strip()
            rest = rest.strip()
            return (head, rest)
    return (right, "")


def detect_diagram_markdown(markdown: str) -> bool:
    """Detector: page(s) contain diagram semantics (arrow or keyword)."""
    if not markdown:
        return False
    if "flow:" in markdown or "diagram" in markdown:
        return True
    for line in markdown.split("\n"):
        if is_relation_line(line):
            return True
        ls = line.strip()
        if any(k in ls for k in ("流程图", "架构图", "架构", "关系图")):
            return True
    return False


def _dedupe_nodes(nodes: list[tuple[str, str]]) -> list[dict]:
    """nodes: [(id0,label)...]; unique by label, stable order."""
    seen: dict[str, str] = {}
    order: list[str] = []
    for label in nodes:
        key = "|" + label
        if key not in seen:
            seen[key] = f"n{len(seen) + 1}"
            order.append(label)
    return [{"id": seen["|" + lbl], "label": lbl} for lbl in order]


def _dedupe_edges(edges: list[tuple[str, str, str]]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for src, tgt, label in edges:
        key = (src, tgt, label)
        if key in seen:
            continue
        seen.add(key)
        out.append({"from": src, "to": tgt, "label": label})
    return out


def infer_flow_from_lines(lines: list[str]) -> tuple[list[dict], list[dict]] | None:
    """Build (nodes, edges) from a list of relation lines (single joined flow).

    Merges a contiguous run of relation lines into ONE flow block — matches how
    a flowchart ``A → B`` / ``B → C`` transcribes as a chain.  Returns None if
    no line yields a usable two-sided relation.
    """
    edgelist: list[tuple[str, str, str]] = []  # (src_label, tgt_label, edge_label)
    for raw in lines:
        parsed = parse_relation_line(raw)
        if parsed is None:
            continue
        src, tgt, label, op = parsed
        edgelist.append((src, tgt, label))
        if op in ("↔", "<->"):
            edgelist.append((tgt, src, label))
    if not edgelist:
        return None
    # node labels in first-appearance order
    node_labels: list[str] = []
    for src, tgt, _ in edgelist:
        for l in (src, tgt):
            if l not in node_labels:
                node_labels.append(l)
    nodes = _dedupe_nodes(node_labels)
    label_to_id = {n["label"]: n["id"] for n in nodes}
    edges = _dedupe_edges(
        [(label_to_id.get(s, s), label_to_id.get(t, t), lbl) for s, t, lbl in edgelist]
    )
    return nodes, edges


def relation_run(lines: list[str], start: int) -> int:
    """Length of the contiguous run of relation lines beginning at ``start``."""
    k = 0
    i = start
    while i < len(lines) and is_relation_line(lines[i]):
        k += 1
        i += 1
    return k


def arrow_flow_block(lines: list[str], start: int) -> dict | None:
    """One block for the relation run at ``start`` (flow if structured, else
    caption-only diagram preserving the text).  Returns a block dict matching
    the IR schema, or None when the line is not a relation line."""
    if start >= len(lines) or not is_relation_line(lines[start]):
        return None
    k = relation_run(lines, start)
    run_lines = [lines[i].strip() for i in range(start, start + k)]
    inferred = infer_flow_from_lines(run_lines)
    if inferred is not None:
        nodes, edges = inferred
        return {
            "type": "flow",
            "orientation": "LR",
            "nodes": nodes,
            "edges": edges,
            "caption": "",
            "source": None,
        }
    # relation-like but not structurally parseable: preserve original text as a
    # caption-only diagram block (no nodes/edges) so nothing is lost.
    return {
        "type": "diagram",
        "nodes": [],
        "edges": [],
        "caption": "\n".join(run_lines),
        "source": None,
    }


__all__ = [
    "is_relation_line",
    "parse_relation_line",
    "detect_diagram_markdown",
    "infer_flow_from_lines",
    "relation_run",
    "arrow_flow_block",
]