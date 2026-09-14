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

# Optional visual-group declaration, e.g. ``[layer] 通信层: macmini, macbook``.
_GROUP_DECL_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?\[\s*(layer|lane|cluster)\s*\]\s*([^:：]+?)\s*[:：]\s*(.+?)\s*$",
    re.IGNORECASE,
)
_GROUP_MEMBER_SPLIT_RE = re.compile(r"[,，、;；|]+")


def is_group_decl(line: str) -> bool:
    """True when ``line`` declares a visual group.

    Syntax: ``[layer|lane|cluster] <label>: <name>, <name> ...`` (leading
    bullet and the Chinese ``：``/``、`` separators are accepted).  The text
    side only has group semantics when the transcription states them
    explicitly; the inferer never invents a hierarchy.
    """
    return bool(_GROUP_DECL_RE.match(line or ""))


def parse_group_decl(line: str) -> dict | None:
    """Parse a group declaration into ``{kind,label,members}`` (members=labels)."""
    m = _GROUP_DECL_RE.match(line or "")
    if not m:
        return None
    kind = m.group(1).lower()
    label = _clean_token(m.group(2))
    members = [
        _clean_token(part)
        for part in _GROUP_MEMBER_SPLIT_RE.split(m.group(3))
    ]
    members = [part for part in members if part]
    if not label:
        return None
    return {"kind": kind, "label": label, "members": members}


def is_graph_source_line(line: str) -> bool:
    """A line that carries graph structure: a relation or a group declaration."""
    return is_relation_line(line) or is_group_decl(line)


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


def _relation_parts(line: str) -> list[tuple[str, str, str]]:
    """Return consecutive ``(left, operator, right)`` pieces from a line.

    Stage-1 transcription often writes a whole chain on one line, e.g.
    ``输入 → 解析 → 输出``.  Splitting the chain before assigning labels keeps
    the middle node from becoming the literal label of the next edge.
    """
    s = line.strip()
    matches = []
    for tok in _RELATION_TOKENS:
        matches.extend((m.start(), m.end(), tok) for m in re.finditer(re.escape(tok), s))
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    # Prefer the longest token at the same position (``-->`` before ``->``).
    chosen: list[tuple[int, int, str]] = []
    for item in matches:
        if chosen and item[0] < chosen[-1][1]:
            continue
        chosen.append(item)
    out: list[tuple[str, str, str]] = []
    for i, (start, end, op) in enumerate(chosen):
        left = _clean_token(s[:start] if i == 0 else s[chosen[i - 1][1]:start])
        right_end = chosen[i + 1][0] if i + 1 < len(chosen) else len(s)
        right = _clean_token(s[end:right_end])
        if left and right:
            out.append((left, op, right))
    return out


def parse_relation_line(line: str) -> tuple[str, str, str, str] | None:
    """Parse ``A → B`` (or ``-->``/``->``/``=>``/``↔``) into (src, tgt, label).

    An optional edge label is taken from ``:``/``：`` after the target
    (``A → B：说明``).  Bidirectional ``A ↔ B`` yields two directed edges in
    the caller.  Returns None when the line has no clear two-sided relation
    (e.g. a bare arrow line with an empty side).
    """
    parts = _relation_parts(line)
    if not parts:
        return None
    left, op, right = parts[0]
    # An edge label is meaningful only on the final target of a simple pair.
    # For chains, the next arrow is a stronger signal than a colon heuristic.
    if len(parts) == 1:
        right, label = _split_label(right)
    else:
        label = ""
    if not right:
        return None
    return (left, right, label, op)


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
    """Detector: page(s) contain diagram semantics (arrow, group or keyword)."""
    if not markdown:
        return False
    if "flow:" in markdown or "diagram" in markdown:
        return True
    for line in markdown.split("\n"):
        if is_relation_line(line) or is_group_decl(line):
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
    no line yields a usable two-sided relation.  Group declarations are ignored
    here; use :func:`infer_graph_from_lines` to also resolve groups.
    """
    return _relations_to_graph(lines)


def _relations_to_graph(
    lines: list[str],
) -> tuple[list[dict], list[dict]] | None:
    edgelist: list[tuple[str, str, str]] = []  # (src_label, tgt_label, edge_label)
    for raw in lines:
        parts = _relation_parts(raw)
        for left, op, right in parts:
            label = ""
            if len(parts) == 1:
                right, label = _split_label(right)
            if not right:
                continue
            if op == "←":
                edgelist.append((right, left, label))
            else:
                edgelist.append((left, right, label))
            if op in ("↔", "<->", "←→", "←->"):
                edgelist.append((right, left, label))
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


def infer_graph_from_lines(
    lines: list[str],
) -> tuple[list[dict], list[dict], list[dict]] | None:
    """Build ``(nodes, edges, groups)`` from relation + group-declaration lines.

    Determinism: group declarations are emitted in text order with ids
    ``g1..gN``; members are resolved by exact node-label match, de-duplicated
    and ordered by node appearance.  Unresolvable member names are dropped and
    no group is fabricated when no declaration exists (empty list).
    """
    graph = _relations_to_graph(lines)
    if graph is None:
        return None
    nodes, edges = graph
    node_index = {n["id"]: i for i, n in enumerate(nodes)}
    label_to_id = {n["label"]: n["id"] for n in nodes}
    groups: list[dict] = []
    for raw in lines:
        decl = parse_group_decl(raw)
        if decl is None:
            continue
        members: list[str] = []
        for name in decl["members"]:
            nid = label_to_id.get(name)
            if nid is None or nid in members:
                continue
            members.append(nid)
        members.sort(key=lambda nid: node_index[nid])
        groups.append({
            "id": f"g{len(groups) + 1}",
            "label": decl["label"],
            "kind": decl["kind"],
            "nodes": members,
        })
    return nodes, edges, groups


def relation_run(lines: list[str], start: int) -> int:
    """Length of the contiguous run of graph-source lines at ``start``."""
    k = 0
    i = start
    while i < len(lines) and is_graph_source_line(lines[i]):
        k += 1
        i += 1
    return k


def relation_lines(lines: list[str]) -> list[str]:
    """Collect graph-source lines (relations and group declarations).

    Bullets and headings frequently interrupt a hand-drawn flow transcription.
    The old contiguous-run rule therefore produced one tiny graph per visual
    row.  The graph is a page-level semantic object, so collect all rows and
    let the structure extractor/layout decide how to arrange them.
    """
    return [line.strip() for line in lines if is_graph_source_line(line)]


def arrow_flow_block(lines: list[str], start: int) -> dict | None:
    """One block for the graph-source run at ``start`` (flow if structured,
    else caption-only diagram preserving the text).  Returns a block dict
    matching the IR schema, or None when the line is not graph-bearing."""
    if start >= len(lines) or not is_graph_source_line(lines[start]):
        return None
    k = relation_run(lines, start)
    run_lines = [lines[i].strip() for i in range(start, start + k)]
    inferred = infer_graph_from_lines(run_lines)
    if inferred is not None:
        nodes, edges, groups = inferred
        return {
            "type": "flow",
            "orientation": "LR",
            "nodes": nodes,
            "edges": edges,
            "caption": "",
            "source": None,
            "groups": groups,
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
    "is_group_decl",
    "is_graph_source_line",
    "parse_group_decl",
    "parse_relation_line",
    "detect_diagram_markdown",
    "infer_flow_from_lines",
    "infer_graph_from_lines",
    "relation_run",
    "relation_lines",
    "arrow_flow_block",
]
