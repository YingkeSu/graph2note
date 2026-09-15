"""Cycle-safe layered layout (longest-path + barycenter), deterministic.

Port of the Spike 3 ``LayerLayout`` productized for the graph2note IR.  Uses
iterative relaxation so cyclic back-edges (loops / 回流) do not recurse into
infinity; ordering only ever depends on node ids (stable tie-breaks).

``grouped_layout`` (SPEC §1) adds *group-aware* placement on top:

- ``layer``  groups share one horizontal band (one row, top-to-bottom reading
  order); band order is derived deterministically from the graph structure,
  never from an ``order`` field the VLM may have produced.  A layer band with
  no incident edge is *flow-isolated* (no structural position): it is anchored
  below every connected band so the reading order is not broken by a phantom
  top band (T-audit F-C).  Only a connected band claims an anchor depth for
  free nodes, so an isolated band can never drag an unrelated source node into
  its sunken row (review N1);
- ``lane``   groups *prefer* one shared vertical column (swimlane) -- each lane
  gets its own column while a base row holds at most one member of that lane;
  extra members landing on the same row overflow into free columns (best
  effort, matching SPEC's "优先同列");
- ``cluster`` groups keep their members adjacent within a row and are reported
  with a local bounding box.

Invariants (golden-tested in ``tests/test_diagram_group_layout.py``):

1. no groups -> rows are exactly ``LayerLayout.layers()`` (regression lock);
2. same semantic input -> byte-identical output (FR-020);
3. layer members share a row; lane members share a column *when no two of them
   share a base row* (see the lane note above);
4. a group's ``bbox`` contains every member position;
5. zero nodes / empty groups / dangling members never raise.

Known limit (F4): when one node belongs to several ``layer`` groups, the
lower-priority group (higher id) still reserves a band; if all of its members
were already claimed by a lower-id group the band is empty yet still counts in
``nrows`` (all rows then spread over that phantom row).  It is deterministic
and harmless for rendering, but callers must not assume ``nrows`` equals the
number of non-empty bands.

Output is a plain, JSON-serialisable dict (the interface shared with D3):

.. code-block:: python

    {
      "positions": {node_id: {"x": float, "y": float}},  # x: left->right, y: top->bottom
      "rows": [[node_id, ...], ...],                      # top -> bottom
      "columns": [[node_id, ...], ...],                   # left -> right
      # NOTE: rows[i] is in barycenter-sweep order, NOT necessarily left->right;
      # use "columns"/"positions" for the actual x axis.
      "groups": [{"id", "label", "kind", "members",
                  "bbox": {"x0", "y0", "x1", "y1"} | None,
                  "row_span": [lo, hi] | None,
                  "col_span": [lo, hi] | None}],
      "node_groups": {node_id: [group_id, ...]},
      "dangling": [member_id, ...],                       # members with no node
      "nrows": int, "ncols": int,
    }
"""

from __future__ import annotations

from . import _canonical


class LayerLayout:
    def __init__(self, node_ids: list[str], edges: list[tuple[str, str]]) -> None:
        self.nid = list(node_ids)
        self.adj: dict[str, list[str]] = {n: [] for n in self.nid}
        self.parents: dict[str, list[str]] = {n: [] for n in self.nid}
        for s, t in edges:
            if s in self.adj and t in self.adj:
                self.adj[s].append(t)
                self.parents[t].append(s)

    def layers(self) -> list[list[str]]:
        # Kahn ranks are monotonic only on the acyclic portion of the graph.
        # The previous repeated-relaxation scheme kept increasing ranks around
        # a back-edge until its hard pass limit, which made cyclic diagrams
        # needlessly wide and put long labels on top of one another.  Edges
        # inside the remaining cycle are routed later, but do not define depth.
        depth: dict[str, int] = {n: 0 for n in self.nid}
        indegree = {n: len(self.parents[n]) for n in self.nid}
        queue = [n for n in self.nid if indegree[n] == 0]
        visited: set[str] = set()
        while queue:
            s = queue.pop(0)
            visited.add(s)
            for t in self.adj[s]:
                depth[t] = max(depth[t], depth[s] + 1)
                indegree[t] -= 1
                if indegree[t] == 0:
                    queue.append(t)

        # Collapse each unresolved cyclic remainder to a stable layer based on
        # its incoming acyclic parents.  This keeps both ends of a back-edge
        # visible instead of manufacturing artificial ranks.
        cyclic = [n for n in self.nid if n not in visited]
        for n in cyclic:
            outside = [p for p in self.parents[n] if p in visited]
            depth[n] = max((depth[p] + 1 for p in outside), default=0)
        maxd = max(depth.values()) if depth else 0
        lay: list[list[str]] = [[] for _ in range(maxd + 1)]
        for n in self.nid:
            lay[depth[n]].append(n)
        # barycenter ordering per layer (stable tie-break on index)
        for i, layer in enumerate(lay):
            centers: dict[str, float] = {}
            for n in layer:
                preds = self.parents[n]
                if preds and i > 0:
                    idxs = [lay[i - 1].index(p) for p in preds if p in lay[i - 1]]
                    centers[n] = (sum(idxs) / len(idxs)) if idxs else float("inf")
                else:
                    centers[n] = float("-inf")
            layer.sort(key=lambda n: (centers[n], self.nid.index(n)))
        return lay

    def positions(self, width: float = 1.0, height: float = 1.0) -> dict[str, tuple[float, float]]:
        lay = self.layers()
        xstep = width / max(1, len(lay))
        pos: dict[str, tuple[float, float]] = {}
        for li, layer in enumerate(lay):
            x = xstep * (li + 0.5)
            ystep = height / max(1, len(layer))
            for yi, n in enumerate(layer):
                y = height - ystep * (yi + 0.5)
                pos[n] = (x, y)
        return pos


# ---------------------------------------------------------------------------
# Group-aware layout (SPEC §1)
# ---------------------------------------------------------------------------


def grouped_layout(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    groups: list | None = None,
    *,
    width: float = 1.0,
    height: float = 1.0,
) -> dict:
    """Lay out ``node_ids``/``edges`` honouring SPEC §1 visual groups.

    ``groups`` are the SPEC JSON shape (dicts) or pydantic-style objects; see
    the module docstring for the returned contract.  When no group survives
    canonicalisation the result is the plain layered layout, i.e. row order is
    exactly ``LayerLayout.layers()`` -- the regression anchor for existing
    diagrams.
    """
    nid = sorted({str(n) for n in node_ids})
    id_set = set(nid)
    edge_pairs = [
        (str(s), str(t)) for s, t in edges if str(s) in id_set and str(t) in id_set
    ]
    dangling = _dangling_members(groups or [], id_set)
    cgroups = _canonical.canonical_groups(list(groups or []), id_set)

    if not nid:
        return _result([], [], cgroups, dangling, width, height)

    if not cgroups:
        rows = [list(layer) for layer in LayerLayout(nid, edge_pairs).layers()]
        return _result(rows, [], cgroups, dangling, width, height)

    # Deterministic anchor: the existing layered layout decides base depth and a
    # within-layer *order position* (base y); groups only re-arrange from there.
    base = LayerLayout(nid, edge_pairs)
    base_layers = base.layers()
    depth = {n: i for i, layer in enumerate(base_layers) for n in layer}
    base_pos = base.positions()
    base_order = {n: base_pos[n][1] for n in nid}  # base within-layer order (not x)

    layer_groups = [g for g in cgroups if g["kind"] == "layer"]
    lane_groups = [g for g in cgroups if g["kind"] == "lane"]
    cluster_groups = [g for g in cgroups if g["kind"] == "cluster"]
    # Unknown kinds degrade to cluster placement (validation is D1's job).
    for g in cgroups:
        if g["kind"] not in ("layer", "lane", "cluster"):
            cluster_groups.append(g)

    layer_owner = _first_owner(layer_groups)
    lane_owner = _first_owner(lane_groups)
    cluster_owner = _first_owner(cluster_groups)

    # -- rows: layer groups occupy one shared band each, ordered by reading --
    anchors = {
        g["id"]: (_median([depth[m] for m in g["nodes"]]) if g["nodes"] else None)
        for g in layer_groups
    }
    # A layer band with no incident edge has no structural position: its median
    # depth is 0, identical to the top band, so band order would interleave it
    # with the first connected band (T-audit F-C: 01 anchor rendered the
    # isolated 执行层 band on the top band).  Sink such flow-isolated bands
    # below every connected band -- deterministic and input-order independent,
    # so the derived reading order stays continuous.  The anchor is unchanged.
    incident = {n for pair in edge_pairs for n in pair}
    isolated = {
        g["id"]: not any(m in incident for m in g["nodes"])
        for g in layer_groups
    }
    effective = sorted(
        (g for g in layer_groups if g["nodes"]),
        key=lambda g: (isolated[g["id"]], anchors[g["id"]], g["id"]),
    )
    entries: list[tuple[int, float, int, str]] = [
        (int(isolated[g["id"]]), float(anchors[g["id"]]), 0, g["id"])
        for g in effective
    ]
    # Only a *connected* layer band owns its anchor depth for free nodes.  An
    # isolated band also has a median depth (usually 0), and letting it claim
    # ``anchor_row[0.0]`` pulled free source nodes into the sunken band row, so
    # their out-edges pointed visually upward (review N1).  A free node whose
    # depth only matches an isolated band now gets its own depth row, ordered
    # above the sunken bands, and no edge is drawn backwards.
    connected_anchors = {
        float(anchors[g["id"]]) for g in effective if not isolated[g["id"]]
    }
    free_depths = sorted(
        {
            depth[n]
            for n in nid
            if n not in layer_owner and float(depth[n]) not in connected_anchors
        }
    )
    entries.extend((0, float(d), 1, f"depth:{d}") for d in free_depths)
    entries.sort(key=lambda e: (e[0], e[1], e[2], e[3]))

    rows: list[list[str]] = [[] for _ in entries]
    group_row: dict[str, int] = {}
    anchor_row: dict[float, int] = {}
    depth_row: dict[int, int] = {}
    for idx, (isolated_flag, anchor, rank, key) in enumerate(entries):
        if rank == 0:
            group_row[key] = idx
            if not isolated_flag:
                anchor_row.setdefault(anchor, idx)
        else:
            depth_row[int(anchor)] = idx

    for n in nid:
        owner = layer_owner.get(n)
        if owner is not None:
            row = group_row[owner]
        else:
            d = depth[n]
            row = anchor_row.get(float(d), depth_row.get(d, 0))
        rows[row].append(n)

    # -- crossing reduction: barycenter sweeps over the free (non-lane) order --
    # Rows are kept in sweep order here; x is assigned from the lane/free column
    # pass below, so rows[i] is not necessarily left-to-right.
    for i, row in enumerate(rows):
        rows[i] = sorted(row, key=lambda n: (base_order[n], n))
    rows = _reduce_crossings(rows, edge_pairs)

    # -- columns: lanes are fixed swimlanes, the rest fill the gaps --
    # A lane keeps its own column only while each base row holds at most one of
    # its members; overflow members fall through to the free columns.
    lane_order = sorted(
        lane_groups,
        key=lambda g: (_mean([base_order[m] for m in g["nodes"]], 0.0), g["id"]),
    )
    lane_col = {g["id"]: i for i, g in enumerate(lane_order)}

    positions: dict[str, dict] = {}
    ncols = max(1, len(lane_order), max((len(r) for r in rows), default=0))
    xs = [(c + 0.5) / ncols * width for c in range(ncols)]
    ys = [(r + 0.5) / max(1, len(rows)) * height for r in range(len(rows))]
    col_members: dict[int, list[str]] = {c: [] for c in range(ncols)}

    for r, row in enumerate(rows):
        taken: dict[int, str] = {}
        free: list[str] = []
        for n in row:
            owner = lane_owner.get(n)
            col = lane_col.get(owner) if owner is not None else None
            if col is not None and col not in taken:
                taken[col] = n
            else:
                free.append(n)
        # Cluster members stay adjacent: cluster key is the primary order,
        # the barycenter-swept order is preserved inside a cluster (stable sort).
        free.sort(key=lambda n: cluster_owner.get(n, "\uffff"))
        for col in (c for c in range(ncols) if c not in taken):
            if not free:
                break
            taken[col] = free.pop(0)
        for col, n in taken.items():
            positions[n] = {"x": xs[col], "y": ys[r]}
            col_members[col].append(n)

    return _result(rows, [col_members[c] for c in range(ncols)],
                   cgroups, dangling, width, height, positions=positions)


def _dangling_members(groups: list, id_set: set[str]) -> list[str]:
    """Member ids referenced by groups but absent from ``nodes[]``."""
    seen: set[str] = set()
    for raw in groups:
        g = _canonical.group_as_dict(raw)
        for m in g.get("nodes") or []:
            m = str(m)
            if m not in id_set:
                seen.add(m)
    return sorted(seen)


def _first_owner(groups: list[dict]) -> dict[str, str]:
    """node_id -> owning group id; the lowest group id wins deterministically."""
    owner: dict[str, str] = {}
    for g in sorted(groups, key=lambda g: g["id"]):
        for m in g["nodes"]:
            owner.setdefault(m, g["id"])
    return owner


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mean(values: list[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default


def _reduce_crossings(
    rows: list[list[str]], edge_pairs: list[tuple[str, str]], passes: int = 2
) -> list[list[str]]:
    """Deterministic barycenter sweeps (down then up, fixed pass count)."""
    nodes = [n for row in rows for n in row]
    preds: dict[str, list[str]] = {n: [] for n in nodes}
    succs: dict[str, list[str]] = {n: [] for n in nodes}
    for s, t in edge_pairs:
        if s in succs and t in preds:
            succs[s].append(t)
            preds[t].append(s)
    for _ in range(passes):
        for r in range(1, len(rows)):
            rows[r] = _order_by_barycenter(rows[r], preds, rows[r - 1])
        for r in range(len(rows) - 2, -1, -1):
            rows[r] = _order_by_barycenter(rows[r], succs, rows[r + 1])
    return rows


def _order_by_barycenter(
    row: list[str], neighbours: dict[str, list[str]], reference: list[str]
) -> list[str]:
    ref_pos = {n: i for i, n in enumerate(reference)}
    cur_pos = {n: i for i, n in enumerate(row)}

    def key(n: str) -> tuple[float, int]:
        vals = [ref_pos[m] for m in neighbours.get(n, ()) if m in ref_pos]
        barycenter = sum(vals) / len(vals) if vals else float(cur_pos[n])
        return (barycenter, cur_pos[n])

    return sorted(row, key=key)


def _result(
    rows: list[list[str]],
    columns: list[list[str]],
    cgroups: list[dict],
    dangling: list[str],
    width: float,
    height: float,
    positions: dict[str, dict] | None = None,
) -> dict:
    """Assemble the public layout dict, filling positions when not supplied."""
    nrows = len(rows)
    ncols = max(1, len(columns), max((len(r) for r in rows), default=0)) if rows else 0
    if positions is None:
        positions = {}
        xs = [(c + 0.5) / ncols * width for c in range(ncols)] if ncols else []
        ys = [(r + 0.5) / nrows * height for r in range(nrows)] if nrows else []
        for r, row in enumerate(rows):
            for c, n in enumerate(row):
                positions[n] = {"x": xs[c], "y": ys[r]}
        columns = [[] for _ in range(ncols)]
        for r, row in enumerate(rows):
            for c, n in enumerate(row):
                columns[c].append(n)

    row_index = {n: i for i, row in enumerate(rows) for n in row}
    col_index = {n: c for c, col in enumerate(columns) for n in col}
    node_groups: dict[str, list[str]] = {n: [] for n in row_index}
    group_boxes = []
    for g in cgroups:
        members = list(g["nodes"])
        for m in members:
            if m in node_groups:
                node_groups[m].append(g["id"])
        pts = [positions[m] for m in members if m in positions]
        if not pts:
            bbox = None
            row_span = None
            col_span = None
        else:
            x0 = min(p["x"] for p in pts)
            x1 = max(p["x"] for p in pts)
            y0 = min(p["y"] for p in pts)
            y1 = max(p["y"] for p in pts)
            # half-cell margin keeps the box visually around the members
            mx = 0.5 * width / max(1, ncols) if ncols else 0.0
            my = 0.5 * height / max(1, nrows) if nrows else 0.0
            bbox = {
                "x0": max(0.0, x0 - mx),
                "y0": max(0.0, y0 - my),
                "x1": min(width, x1 + mx),
                "y1": min(height, y1 + my),
            }
            rs = sorted(row_index[m] for m in members if m in row_index)
            cs = sorted(col_index[m] for m in members if m in col_index)
            row_span = [rs[0], rs[-1]] if rs else None
            col_span = [cs[0], cs[-1]] if cs else None
        group_boxes.append({
            "id": g["id"],
            "label": g.get("label", ""),
            "kind": g["kind"],
            "members": members,
            "bbox": bbox,
            "row_span": row_span,
            "col_span": col_span,
        })

    return {
        "positions": positions,
        "rows": [list(r) for r in rows],
        "columns": [list(c) for c in columns],
        "groups": group_boxes,
        "node_groups": node_groups,
        "dangling": dangling,
        "nrows": nrows,
        "ncols": ncols,
    }
