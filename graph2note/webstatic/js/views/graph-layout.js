/* graph2note — knowledge-graph layout engine (U4).

   Pure functions only: no DOM, no network, no build step.  `graph.js` renders
   what this module computes, and `tests/graph_layout.mjs` drives the same
   functions under Node, so the "no node bounding-box overlap" acceptance
   criterion is a programmatic assertion rather than an eyeball check.

   Zero-build / no external graph library: the force-directed relaxation plus
   the bounding-box separation pass below are written here in ~150 lines.

   Coordinate contract: everything is in *layout units*.  The first generation
   pass produces absolute pixel-like positions (origin at 0); the second pass
   re-scales them into a viewBox anchored at 0 with a fixed margin, so nodes
   never sit at the edge and `viewBox="0 0 width height"` always works.
*/

"use strict";

/* ---------- visual constants (shared with graph.js and the tests) ---------- */

export const LAYOUT = {
  documentRadius: 34,
  topicRadius: 30,
  tagRadius: 30,
  clusterRadius: 32,
  collectionRadius: 30,
  labelCharWidth: 18,
  labelHeight: 22,
  labelPadX: 10,
  labelPadY: 3,
  maxLabelChars: 7,
  nodeGap: 14,
  margin: 36,
  iterations: 240,
  separationPasses: 800,
  seed: 0x9e3779b9,
};

/* Above this many visible nodes the view converges documents into topic
   clusters by default (U4 AC3: "文档数多时默认视图做聚类收敛"). */
export const CLUSTER_THRESHOLD = 24;

/* The force-relaxed layout is uniformly compressed to this span before the
   separation pass, which keeps node text readable at the default (fit) zoom. */
export const TARGET_SPAN = 640;

/* Zoom window is expressed as a viewBox scale factor; 1 = fit to viewport. */
export const MIN_ZOOM = 0.25;
export const MAX_ZOOM = 4;
export const ZOOM_STEPS = 10;
export const ZOOM_STEP_RATIO = Math.pow(2, 1 / ZOOM_STEPS);

export function nodeRadius(node) {
  if (!node) return LAYOUT.topicRadius;
  if (node.kind === "document") return LAYOUT.documentRadius;
  if (node.kind === "cluster") return LAYOUT.clusterRadius;
  if (node.kind === "collection") return LAYOUT.collectionRadius;
  if (node.kind === "tag") return LAYOUT.tagRadius;
  return LAYOUT.topicRadius;
}

function labelText(node) {
  if (!node) return "";
  const raw = node.kind === "cluster" ? `▣ ${node.label}` : node.label;
  const text = raw == null ? "" : String(raw);
  if (text.length <= LAYOUT.maxLabelChars) return text;
  return text.slice(0, LAYOUT.maxLabelChars - 1) + "…";
}

export function labelWidth(node) {
  const chars = Math.max(1, labelText(node).length);
  return Math.min(chars * LAYOUT.labelCharWidth, 2 * nodeRadius(node) + LAYOUT.labelCharWidth);
}

/* The node's bounding box in layout units.  Labels render at 18px inside the
   circle, so for CJK text the glyph run can be taller/wider than the circle
   (`labelCharWidth` is a conservative estimate of one glyph's advance).  The box
   is therefore the union of the circle and the reserved label rectangle — the
   same definition feeds the renderer, the separation solver and the overlap
   assertion, so "no bounding-box overlap" is measured against exactly what the
   user sees. */
export function nodeBox(node, x, y) {
  const radius = nodeRadius(node);
  const halfWidth = Math.max(radius, labelWidth(node) / 2 + LAYOUT.labelPadX);
  const halfHeight = Math.max(radius, LAYOUT.labelHeight / 2 + LAYOUT.labelPadY);
  return { left: x - halfWidth, right: x + halfWidth, top: y - halfHeight, bottom: y + halfHeight };
}

export function boxesIntersect(a, b) {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/* Count intersecting node boxes over a `positions` map (id -> {x,y}). */
export function overlapCount(nodes, positions) {
  const boxes = [];
  for (const node of nodes || []) {
    const point = positions[node.id];
    if (!point) continue;
    boxes.push({ id: node.id, ...nodeBox(node, point.x, point.y) });
  }
  let overlaps = 0;
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      if (boxesIntersect(boxes[i], boxes[j])) overlaps += 1;
    }
  }
  return overlaps;
}

export function findOverlaps(nodes, positions) {
  const boxes = [];
  for (const node of nodes || []) {
    const point = positions[node.id];
    if (!point) continue;
    boxes.push({ a: node.id, ...nodeBox(node, point.x, point.y) });
  }
  const pairs = [];
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      if (boxesIntersect(boxes[i], boxes[j])) pairs.push([boxes[i].a, boxes[j].a]);
    }
  }
  return pairs;
}

/* ---------- determinism ---------- */

function makeRandom(seed) {
  let state = (Number(seed) || LAYOUT.seed) >>> 0;
  return function random() {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function sortNodes(nodes) {
  const order = { document: 0, cluster: 1, topic: 2, tag: 3, collection: 4 };
  return [...(nodes || [])].sort((a, b) => {
    const ka = order[a.kind] == null ? 9 : order[a.kind];
    const kb = order[b.kind] == null ? 9 : order[b.kind];
    if (ka !== kb) return ka - kb;
    const la = String(a.label == null ? "" : a.label).toLowerCase();
    const lb = String(b.label == null ? "" : b.label).toLowerCase();
    if (la !== lb) return la < lb ? -1 : 1;
    return String(a.id) < String(b.id) ? -1 : 1;
  });
}

/* ---------- connected components (union-find) ---------- */

function buildComponents(nodes, edges) {
  const parent = new Map(nodes.map((node) => [node.id, node.id]));
  const find = (id) => {
    let root = id;
    while (parent.get(root) !== root) root = parent.get(root);
    while (parent.get(id) !== root) { const next = parent.get(id); parent.set(id, root); id = next; }
    return root;
  };
  const union = (a, b) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent.set(ra, rb);
  };
  for (const edge of edges || []) {
    if (parent.has(edge.from) && parent.has(edge.to)) union(edge.from, edge.to);
  }
  const groups = new Map();
  for (const node of nodes) {
    const root = find(node.id);
    if (!groups.has(root)) groups.set(root, []);
    groups.get(root).push(node.id);
  }
  return [...groups.values()].sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
}

/* ---------- quality metrics (used by the evidence probe / tests) ---------- */

export function layoutMetrics(positions) {
  const points = Object.values(positions || {});
  if (!points.length) {
    return { width: 0, height: 0, centerX: 0, centerY: 0, meanEdgeLength: 0, count: 0 };
  }
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const width = Math.max(...xs) - Math.min(...xs);
  const height = Math.max(...ys) - Math.min(...ys);
  return {
    width: Math.round(width * 100) / 100,
    height: Math.round(height * 100) / 100,
    centerX: (Math.max(...xs) + Math.min(...xs)) / 2,
    centerY: (Math.max(...ys) + Math.min(...ys)) / 2,
    meanEdgeLength: 0,
    count: points.length,
  };
}

/* ---------- force-directed layout ---------- */

const KIND_BAND = { document: 0, cluster: 1, topic: 2, tag: 3, collection: 4 };

function initialPositions(nodes, edges, seed) {
  const random = makeRandom(seed);
  const positions = new Map();
  const components = buildComponents(nodes, edges);
  const columns = Math.max(1, Math.ceil(Math.sqrt(components.length)));
  const cellW = 640;
  const cellH = 540;

  components.forEach((ids, index) => {
    const cx = ((index % columns) - (columns - 1) / 2) * cellW;
    const cy = (Math.floor(index / columns) - (components.length / columns - 1) / 2) * cellH;
    const byKind = new Map();
    for (const id of ids) {
      const node = nodes.find((item) => item.id === id);
      const band = KIND_BAND[node.kind] == null ? 2 : KIND_BAND[node.kind];
      if (!byKind.has(band)) byKind.set(band, []);
      byKind.get(band).push(node);
    }
    for (const [band, members] of [...byKind.entries()].sort((a, b) => a[0] - b[0])) {
      const radius = band === 0 ? 0 : 70 * band + 34 * band;
      const step = (2 * Math.PI) / Math.max(1, members.length);
      members.forEach((node, i) => {
        const angle = i * step + band * 0.4;
        positions.set(node.id, {
          x: cx + radius * Math.cos(angle) + (random() - 0.5) * 24,
          y: cy + radius * Math.sin(angle) + (random() - 0.5) * 24,
        });
      });
    }
  });
  return positions;
}

function relax(nodes, edges, positions, random) {
  const ids = nodes.map((node) => node.id);
  const index = new Map(ids.map((id, i) => [id, i]));
  const px = new Float64Array(ids.length);
  const py = new Float64Array(ids.length);
  const vx = new Float64Array(ids.length);
  const vy = new Float64Array(ids.length);
  const degree = new Float64Array(ids.length);
  ids.forEach((id, i) => {
    const point = positions.get(id);
    px[i] = point.x;
    py[i] = point.y;
  });

  const springs = [];
  for (const edge of edges || []) {
    const a = index.get(edge.from);
    const b = index.get(edge.to);
    if (a == null || b == null || a === b) continue;
    springs.push([a, b]);
    degree[a] += 1;
    degree[b] += 1;
  }

  const repulsion = 9000;
  const repulsionCutoff = 460;
  const springLength = 165;
  const springStrength = 0.035;
  const gravity = 0.0015;
  const maxStep = 42;
  const iterations = LAYOUT.iterations;

  for (let step = 0; step < iterations; step += 1) {
    const cooling = 1 - (step / iterations) * 0.55;
    const fx = new Float64Array(ids.length);
    const fy = new Float64Array(ids.length);

    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        let dx = px[i] - px[j];
        let dy = py[i] - py[j];
        let distance = Math.hypot(dx, dy);
        if (distance > repulsionCutoff) continue;
        if (distance < 0.5) {
          dx = (random() - 0.5) || 0.5;
          dy = (random() - 0.5) || 0.5;
          distance = Math.hypot(dx, dy);
        }
        const force = repulsion / (distance * distance);
        const ux = dx / distance;
        const uy = dy / distance;
        fx[i] += ux * force;
        fy[i] += uy * force;
        fx[j] -= ux * force;
        fy[j] -= uy * force;
      }
    }

    for (const [a, b] of springs) {
      const dx = px[b] - px[a];
      const dy = py[b] - py[a];
      const distance = Math.max(1, Math.hypot(dx, dy));
      const force = (distance - springLength) * springStrength;
      const ux = dx / distance;
      const uy = dy / distance;
      fx[a] += ux * force;
      fy[a] += uy * force;
      fx[b] -= ux * force;
      fy[b] -= uy * force;
    }

    for (let i = 0; i < ids.length; i += 1) {
      fx[i] -= px[i] * gravity;
      fy[i] -= py[i] * gravity;
    }

    for (let i = 0; i < ids.length; i += 1) {
      vx[i] = (vx[i] + fx[i]) * 0.85;
      vy[i] = (vy[i] + fy[i]) * 0.85;
      const speed = Math.hypot(vx[i], vy[i]);
      if (speed > maxStep) {
        vx[i] = (vx[i] / speed) * maxStep;
        vy[i] = (vy[i] / speed) * maxStep;
      }
      px[i] += vx[i] * cooling;
      py[i] += vy[i] * cooling;
    }
  }

  ids.forEach((id, i) => { positions.set(id, { x: px[i], y: py[i] }); });
}

/* Bounding-box separation: the hard guarantee behind AC1.

   Nodes are treated as inflated by half the required gap, so the solver not
   only removes intersections but leaves a visible breathing space between every
   pair (two boxes are only "settled" once they are at least ``gap`` apart).
   Each pass accumulates a displacement per node from every violating pair
   (equal-and-opposite along the axis of least penetration) and applies it with
   damping, so the solver relaxes into a gap-respecting arrangement instead of
   oscillating between two cramped configurations.  A uniform spatial hash keeps
   each pass near-linear for the ~50-300 node libraries we target, and the loop
   only exits once no pair violates the gap. */
function separate(nodes, positions, gap = LAYOUT.nodeGap) {
  const cell = 96;
  const damping = 0.8;
  const maxStepPerPass = 36;
  const pad = gap / 2;
  const inflate = (box) => ({
    left: box.left - pad, right: box.right + pad,
    top: box.top - pad, bottom: box.bottom + pad,
  });
  for (let pass = 0; pass < LAYOUT.separationPasses; pass += 1) {
    const shiftX = new Float64Array(nodes.length);
    const shiftY = new Float64Array(nodes.length);
    const grid = new Map();
    const boxes = nodes.map((node, index) => {
      const point = positions.get(node.id);
      const box = inflate(nodeBox(node, point.x, point.y));
      box.index = index;
      return box;
    });
    boxes.forEach((box, index) => {
      const minX = Math.floor(box.left / cell);
      const maxX = Math.floor(box.right / cell);
      const minY = Math.floor(box.top / cell);
      const maxY = Math.floor(box.bottom / cell);
      for (let gx = minX; gx <= maxX; gx += 1) {
        for (let gy = minY; gy <= maxY; gy += 1) {
          const key = `${gx}:${gy}`;
          if (!grid.has(key)) grid.set(key, []);
          grid.get(key).push(index);
        }
      }
    });

    let moved = false;
    for (let i = 0; i < boxes.length; i += 1) {
      const a = boxes[i];
      const candidates = new Set();
      const minX = Math.floor(a.left / cell);
      const maxX = Math.floor(a.right / cell);
      const minY = Math.floor(a.top / cell);
      const maxY = Math.floor(a.bottom / cell);
      for (let gx = minX; gx <= maxX; gx += 1) {
        for (let gy = minY; gy <= maxY; gy += 1) {
          for (const j of grid.get(`${gx}:${gy}`) || []) {
            if (j > i) candidates.add(j);
          }
        }
      }
      for (const j of candidates) {
        const b = boxes[j];
        if (!boxesIntersect(a, b)) continue;
        moved = true;
        const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (overlapX <= overlapY) {
          const shift = (overlapX / 2) * damping;
          if (a.index < b.index) { shiftX[a.index] -= shift; shiftX[b.index] += shift; }
          else { shiftX[b.index] -= shift; shiftX[a.index] += shift; }
        } else {
          const shift = (overlapY / 2) * damping;
          if (a.index < b.index) { shiftY[a.index] -= shift; shiftY[b.index] += shift; }
          else { shiftY[b.index] -= shift; shiftY[a.index] += shift; }
        }
      }
    }
    if (!moved) return;
    for (let i = 0; i < nodes.length; i += 1) {
      const stepX = Math.max(-maxStepPerPass, Math.min(maxStepPerPass, shiftX[i]));
      const stepY = Math.max(-maxStepPerPass, Math.min(maxStepPerPass, shiftY[i]));
      if (stepX === 0 && stepY === 0) continue;
      const point = positions.get(nodes[i].id);
      positions.set(nodes[i].id, { x: point.x + stepX, y: point.y + stepY });
    }
  }
}

/* Re-anchor and rescale so the *force-relaxed* layout fits a compact target
   before the separation pass runs.  Doing it in this order matters: the
   separation gap is enforced in final viewBox units, so scaling afterwards
   could shrink nodes back into each other. */
function fitToViewBox(nodes, positions) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of nodes) {
    const point = positions.get(node.id);
    const box = nodeBox(node, point.x, point.y);
    minX = Math.min(minX, box.left);
    minY = Math.min(minY, box.top);
    maxX = Math.max(maxX, box.right);
    maxY = Math.max(maxY, box.bottom);
  }
  if (!Number.isFinite(minX)) return { width: 320, height: 240 };
  const contentWidth = Math.max(1, maxX - minX);
  const contentHeight = Math.max(1, maxY - minY);
  const scale = Math.min(TARGET_SPAN / contentWidth, TARGET_SPAN / contentHeight, 1);
  for (const node of nodes) {
    const point = positions.get(node.id);
    positions.set(node.id, { x: (point.x - minX) * scale, y: (point.y - minY) * scale });
  }
  return { width: contentWidth * scale, height: contentHeight * scale, scale };
}

/* Final framing: translate the (already separated) layout to the origin with a
   uniform margin, without rescaling — the separation gap is preserved exactly
   as measured by `overlapCount`. */
function finalFrame(nodes, positions, gap) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of nodes) {
    const point = positions.get(node.id);
    const box = nodeBox(node, point.x, point.y);
    minX = Math.min(minX, box.left);
    minY = Math.min(minY, box.top);
    maxX = Math.max(maxX, box.right);
    maxY = Math.max(maxY, box.bottom);
  }
  const margin = gap + LAYOUT.margin;
  for (const node of nodes) {
    const point = positions.get(node.id);
    positions.set(node.id, { x: point.x - minX + margin, y: point.y - minY + margin });
  }
  return { width: Math.max(1, maxX - minX) + margin * 2, height: Math.max(1, maxY - minY) + margin * 2 };
}

/* Solve a layout from an explicit seed map (seededSolve), or from the
   deterministic force relaxation (computeLayout).  Kept in one place so the
   clustered graph and the raw graph go through the exact same separation
   guarantee. */
function solveFromSeeds(nodes, edges, seedPositions) {
  const positions = new Map(seedPositions);
  fitToViewBox(nodes, positions);
  const gap = LAYOUT.nodeGap;
  separate(nodes, positions, gap);
  const { width, height } = finalFrame(nodes, positions, gap);
  return {
    width: Math.round(width), height: Math.round(height),
    positions: Object.fromEntries(positions),
    nodes: sortNodes(nodes), edges, gap,
  };
}

/* Continuation-based layout used by the cluster view: the force solver already
   produced the (already framed) expanded layout, so the clustered graph is
   relaxed from the aggregate centroids and then separated in place. */
export function solveFromPositions(nodesInput, edgesInput, seedPositions) {
  const nodes = sortNodes(nodesInput);
  const edges = (edgesInput || []).filter(
    (edge) => nodes.some((node) => node.id === edge.from) && nodes.some((node) => node.id === edge.to),
  );
  const seeds = new Map();
  for (const node of nodes) {
    const point = seedPositions[node.id];
    if (point) seeds.set(node.id, { x: point.x, y: point.y });
  }
  return solveFromSeeds(nodes, edges, seeds);
}

export function computeLayout(nodesInput, edgesInput, options = {}) {
  const nodes = sortNodes(nodesInput);
  const edges = [...(edgesInput || [])].sort((a, b) => {
    const ka = `${a.source}\u0000${a.from}\u0000${a.to}`;
    const kb = `${b.source}\u0000${b.from}\u0000${b.to}`;
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  });
  if (!nodes.length) {
    return { width: 320, height: 240, positions: {}, nodes, edges, gap: LAYOUT.nodeGap };
  }
  const random = makeRandom(options.seed == null ? LAYOUT.seed : options.seed);
  const positions = initialPositions(nodes, edges, options.seed);
  relax(nodes, edges, positions, random);
  return solveFromSeeds(nodes, edges, positions);
}

/* ---------- derived view state ---------- */

/* Filter the raw API graph down to the visible subgraph.

   `filters.sources` is a Set (or array) of edge provenances to keep;
   `filters.collections` / `filters.tags` are sets of selected document ids —
   when a selection exists only documents matching **all** selections survive,
   and nodes that end up with no surviving edge are pruned (a subgraph only
   shows what the filter selected).  With no selection every node stays visible
   so lone documents remain reachable. */
export function subgraph(payload, filters = {}) {
  const allNodes = (payload && payload.nodes) || [];
  const allEdges = (payload && payload.edges) || [];
  const sources = filters.sources instanceof Set
    ? filters.sources
    : new Set(filters.sources || ["topic", "tag", "manual"]);
  const collections = filters.collections instanceof Set
    ? new Set(filters.collections)
    : new Set(filters.collections || []);
  const tags = filters.tags instanceof Set
    ? new Set(filters.tags)
    : new Set(filters.tags || []);
  const topic = filters.topic == null ? null : String(filters.topic);
  const hasSelection = collections.size > 0 || tags.size > 0 || Boolean(topic);

  const sourceOk = (edge) => sources.has(edge.source);

  const documentMatches = (documentId) => {
    if (!hasSelection) return true;
    if (collections.size) {
      const collectionsOfDoc = new Set(
        allEdges.filter((edge) => edge.document_id === documentId
          && edge.source === "manual" && edge.collection_id != null)
          .map((edge) => edge.collection_id),
      );
      for (const selected of collections) if (!collectionsOfDoc.has(selected)) return false;
    }
    if (tags.size) {
      const tagsOfDoc = new Set(
        allEdges.filter((edge) => edge.document_id === documentId && edge.source === "tag")
          .map((edge) => edge.tag),
      );
      for (const selected of tags) if (!tagsOfDoc.has(selected)) return false;
    }
    if (topic) {
      const topicsOfDoc = new Set(
        allEdges.filter((edge) => edge.document_id === documentId && edge.source === "topic")
          .map((edge) => edge.topic),
      );
      if (!topicsOfDoc.has(topic)) return false;
    }
    return true;
  };

  const visible = new Set();
  for (const node of allNodes) {
    if (node.kind === "document") {
      if (documentMatches(node.document_id)) visible.add(node.id);
    } else {
      visible.add(node.id);
    }
  }

  // Edges from active sources between two candidate endpoints decide which
  // topic/tag/collection nodes still belong; non-documents without a drawn edge
  // are pruned, while untouched documents keep the issue-05 "lone document"
  // navigability.
  let edges = allEdges.filter((edge) => sourceOk(edge)
    && visible.has(edge.from) && visible.has(edge.to));
  const connected = new Set();
  for (const edge of edges) {
    connected.add(edge.from);
    connected.add(edge.to);
  }
  for (const node of allNodes) {
    if (node.kind === "document") continue;
    if (!connected.has(node.id)) visible.delete(node.id);
  }

  const nodeIds = new Set([...visible]);
  edges = allEdges.filter((edge) => sourceOk(edge)
    && nodeIds.has(edge.from) && nodeIds.has(edge.to));

  const nodes = allNodes.filter((node) => visible.has(node.id));
  return { nodes, edges };
}

/* Collapse documents into topic clusters.  Collapsed members are replaced by
   one aggregate node at the centroid of their *computed* positions; edges that
   used to touch a member are re-pointed at the aggregate (deduplicated).
   `positions` is the layout of the un-collapsed visible subgraph, `expanded`
   is the set of cluster ids the user opened inline. */
export function applyClusters(view, payload, positions, collapsed, expanded = new Set()) {
  const clusters = (payload && payload.clusters) || [];
  if (!collapsed || !clusters.length) return view;
  const nodeById = new Map(view.nodes.map((node) => [node.id, node]));
  const hidden = new Map();
  const aggregateNodes = [];
  const clusterPositions = {};
  for (const cluster of clusters) {
    if (expanded.has(cluster.id)) continue;
    const memberIds = cluster.documents
      .map((id) => `document:${id}`)
      .filter((id) => nodeById.has(id) && positions[id]);
    if (!memberIds.length) continue;
    const centroid = { x: 0, y: 0 };
    for (const memberId of memberIds) {
      centroid.x += positions[memberId].x;
      centroid.y += positions[memberId].y;
    }
    centroid.x /= memberIds.length;
    centroid.y /= memberIds.length;
    aggregateNodes.push({
      id: cluster.id,
      kind: "cluster",
      label: cluster.label,
      route: cluster.route,
      cluster: true,
      size: cluster.size,
      documentCount: cluster.size,
      memberIds,
    });
    clusterPositions[cluster.id] = centroid;
    for (const memberId of memberIds) hidden.set(memberId, cluster.id);
  }

  // re-point edges through the aggregate, dropping intra-cluster duplicates
  const remapped = new Map();
  for (const edge of view.edges) {
    const from = hidden.get(edge.from) || edge.from;
    const to = hidden.get(edge.to) || edge.to;
    if (from === to) continue;
    const key = `${from}|${edge.source}|${to}`;
    if (remapped.has(key)) continue;
    remapped.set(key, { ...edge, from, to, id: `${edge.source}:${from}->${to}` });
  }

  const nodes = [...view.nodes.filter((node) => !hidden.has(node.id)), ...aggregateNodes];
  return {
    nodes,
    edges: [...remapped.values()],
    hidden,
    aggregates: aggregateNodes,
    clusterPositions,
  };
}

/* Neighbourhood of `focusId` (1-hop, seeded from the current subgraph). */
export function focusSet(nodes, edges, focusId) {
  const nodeIds = new Set((nodes || []).map((node) => node.id));
  if (!focusId || !nodeIds.has(focusId)) return null;
  const active = new Set([focusId]);
  for (const edge of edges || []) {
    if (edge.from === focusId) active.add(edge.to);
    else if (edge.to === focusId) active.add(edge.from);
  }
  const check = {};
  for (const node of nodes || []) check[node.id] = active.has(node.id);
  return { activeNodes: active, byId: check };
}

/* ---------- zoom / pan transforms (pure, unit-tested) ---------- */

export function clampZoom(scale) {
  const value = Number(scale);
  if (!Number.isFinite(value) || value <= 0) return 1;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

/* Layout viewBox for a given zoom factor.  1 = the fitted layout. */
export function viewBoxFor(layout, zoom) {
  const scale = clampZoom(zoom);
  const width = Math.max(1, (layout && layout.width) || 1) / scale;
  const height = Math.max(1, (layout && layout.height) || 1) / scale;
  return { x: 0, y: 0, width, height };
}

export function viewBoxString(layout, zoom) {
  const box = viewBoxFor(layout, zoom);
  return `${box.x} ${box.y} ${box.width} ${box.height}`;
}

/* Pointer -> layout coordinates for the current viewBox (used by drag pan and
   wheel zoom).  Mirrors SVG's preserveAspectRatio="xMidYMid meet" mapping. */
export function pointerToLayout(clientX, clientY, rect, layout, zoom) {
  const box = viewBoxFor(layout, zoom);
  const scale = Math.min(rect.width / box.width, rect.height / box.height);
  const offsetX = (rect.width - box.width * scale) / 2;
  const offsetY = (rect.height - box.height * scale) / 2;
  return { x: (clientX - rect.left - offsetX) / scale, y: (clientY - rect.top - offsetY) / scale };
}

/* Zoom about a fixed layout point so the cursor stays over the same node: the
   point's fractional position inside the viewBox is preserved across the step. */
export function zoomedViewBox(layout, zoom, pan, factor, anchor) {
  const nextZoom = clampZoom(zoom * factor);
  const before = viewBoxFor(layout, zoom);
  const after = viewBoxFor(layout, nextZoom);
  const point = anchor || { x: before.x + before.width / 2, y: before.y + before.height / 2 };
  const rx = (point.x - pan.x) / before.width;
  const ry = (point.y - pan.y) / before.height;
  const nextPan = { x: point.x - rx * after.width, y: point.y - ry * after.height };
  return { zoom: nextZoom, pan: nextPan, viewBox: `${nextPan.x} ${nextPan.y} ${after.width} ${after.height}` };
}

export function panBy(layout, zoom, pan, dx, dy) {
  const box = viewBoxFor(layout, zoom);
  const nextPan = { x: pan.x + dx * box.width, y: pan.y + dy * box.height };
  return { pan: nextPan, viewBox: `${nextPan.x} ${nextPan.y} ${box.width} ${box.height}` };
}

export function label(text) {
  return labelText({ kind: "document", label: text });
}
