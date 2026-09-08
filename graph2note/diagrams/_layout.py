"""Cycle-safe layered layout (longest-path + barycenter), deterministic.

Port of the Spike 3 ``LayerLayout`` productized for the graph2note IR.  Uses
iterative relaxation so cyclic back-edges (loops / 回流) do not recurse into
infinity; ordering only ever depends on node ids (stable tie-breaks).
"""

from __future__ import annotations


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
        depth: dict[str, int] = {n: 0 for n in self.nid}
        for _ in range(len(self.nid) + 2):  # enough passes for any acyclic graph
            changed = False
            for s in self.nid:
                for t in self.adj[s]:
                    if depth[t] < depth[s] + 1:
                        depth[t] = depth[s] + 1
                        changed = True
            if not changed:
                break
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
