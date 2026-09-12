/* graph2note — knowledge-graph view (issue 05, upgraded in U4).

   U4 adds, on top of the read-only projection:
     - a deterministic force-directed layout with a hard bounding-box
       separation pass (zero node overlap, see graph-layout.js),
     - wheel zoom (0.25x–4x), drag pan, fit/reset/zoom buttons,
     - source / collection / tag filters with visible status chips,
     - topic-cluster convergence for large libraries (click to expand),
     - 1-hop neighbourhood focus (click a node, click empty space to clear).

   Navigation semantics are unchanged: documents -> three-pane editor,
   topics -> filtered document list, tags -> tag filter.  Everything is driven
   by the URL (`#graph?src=&set=&tag=&focus=&clusters=`) so back/forward and
   direct links keep working.  Zero build step, no external graph library.
*/
"use strict";

import { el } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { go, registerView, graphHash } from "../router.js";
import { showViewError, clearViewError, showToast } from "../ui.js";
import {
  CLUSTER_THRESHOLD,
  LAYOUT,
  ZOOM_STEP_RATIO,
  applyClusters,
  computeLayout,
  focusSet,
  nodeRadius,
  pointerToLayout,
  solveFromPositions,
  subgraph,
  zoomedViewBox,
} from "./graph-layout.js";

const GRAPH_EDGE_COLORS = { topic: "#4f7fe8", tag: "#c07a1a", manual: "#16836d" };
const GRAPH_KIND_LABELS = {
  document: "文档", topic: "主题", tag: "标签", collection: "集合", cluster: "主题聚类",
};
const ALL_SOURCES = ["topic", "tag", "manual"];

/* View-local state.  Nothing here is shared with other views. */
export const view = {
  payload: null,
  subgraph: null,
  layout: null,
  rendered: null,
  version: 0,
  filters: { sources: new Set(ALL_SOURCES), collections: new Set(), tags: new Set() },
  topic: null,
  focusId: null,
  expanded: new Set(),
  clusters: "auto",
  zoom: 1,
  pan: { x: 0, y: 0 },
};

/* ---------- small helpers ---------- */

function canvasPoint(event) {
  const ctm = el.graphCanvas.getScreenCTM();
  if (!ctm) return { x: view.pan.x, y: view.pan.y };
  const point = el.graphCanvas.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  return point.matrixTransform(ctm.inverse());
}

function applyViewBox() {
  const box = viewBoxFor();
  el.graphCanvas.setAttribute("viewBox", `${box.x} ${box.y} ${box.width} ${box.height}`);
  if (el.graphZoomValue) el.graphZoomValue.textContent = `${Math.round(view.zoom * 100)}%`;
  if (el.graphCanvas) {
    el.graphCanvas.dataset.zoom = String(view.zoom);
    el.graphCanvas.dataset.panX = String(Math.round(view.pan.x));
    el.graphCanvas.dataset.panY = String(Math.round(view.pan.y));
  }
}

/* The viewBox always tracks the *rendered* layout (clustered aggregates are
   re-solved, so their dimensions can differ from the pre-aggregation layout).
   Zoom, pan and fit all read this one accessor so they can never disagree. */
function currentLayout() {
  return (view.rendered && view.rendered.layout)
    || view.layout || { width: 320, height: 240 };
}

function viewBoxFor() {
  const layout = currentLayout();
  const width = Math.max(1, layout.width) / view.zoom;
  const height = Math.max(1, layout.height) / view.zoom;
  return { x: view.pan.x, y: view.pan.y, width, height };
}

/* ---------- render pipeline ---------- */

function activeSubgraph() {
  return subgraph(view.payload, {
    sources: view.filters.sources,
    collections: view.filters.collections,
    tags: view.filters.tags,
    topic: view.topic,
  });
}

function computeView() {
  view.subgraph = activeSubgraph();
  view.layout = computeLayout(view.subgraph.nodes, view.subgraph.edges);
  const collapse = view.clusters !== "expand"
    && (view.clusters === "collapse" || view.subgraph.nodes.length > CLUSTER_THRESHOLD);
  const collapsed = applyClusters(view.subgraph, view.payload, view.layout.positions,
    collapse, view.expanded);
  if (collapsed.aggregates && collapsed.aggregates.length) {
    // aggregate nodes are placed from member centroids, then re-separated so the
    // converged view keeps the same zero-overlap guarantee
    const seeded = { ...view.layout.positions, ...collapsed.clusterPositions };
    const relayout = solveFromPositions(collapsed.nodes, collapsed.edges, seeded);
    view.rendered = { ...collapsed, positions: relayout.positions, layout: relayout };
  } else {
    view.rendered = { ...view.subgraph, positions: view.layout.positions, aggregates: [] };
  }
}

function nodeTooltip(node) {
  if (node.kind === "cluster") {
    return `${node.label} · 主题聚类 · ${node.documentCount} 份文档 · 单击展开`;
  }
  const routeHint = node.kind === "document"
    ? "单击聚焦邻域、双击进入编辑器"
    : "单击在文档库中过滤";
  return `${node.label} · ${GRAPH_KIND_LABELS[node.kind] || node.kind} · ${node.degree || 0} 条关系 · ${routeHint}`;
}

function nodesHtml(list, positions, active) {
  return list.map((node) => {
    const point = positions[node.id] || { x: 0, y: 0 };
    const radius = nodeRadius(node);
    const label = nodeText(node);
    const classes = [
      "graph-node",
      `graph-node-${node.kind}`,
      node.isolated ? "isolated" : "",
      active && !active.byId[node.id] ? "faded" : "",
    ].filter(Boolean).join(" ");
    const attributes = [
      `class="${classes}"`,
      `data-node-id="${esc(node.id)}"`,
      node.kind === "cluster" ? `data-cluster="${esc(node.id)}"` : `data-route="${esc(node.route)}"`,
      `data-kind="${esc(node.kind)}"`,
      'role="button"',
      'tabindex="0"',
      `transform="translate(${point.x} ${point.y})"`,
    ].join(" ");
    const aggregate = node.kind === "cluster"
      ? `<circle class="graph-cluster-halo" r="${radius + 7}"></circle>`
      : "";
    return `<g ${attributes}>
      <title>${esc(nodeTooltip(node))}</title>
      ${aggregate}
      <circle r="${radius}"></circle>
      <text text-anchor="middle" dy="4">${esc(label)}</text>
    </g>`;
  }).join("");
}

/* Keep the rendered label inside the box `nodeBox()` reserved for it: the
   layout engine and the renderer share LAYOUT.maxLabelChars. */
function nodeText(node) {
  const prefix = node.kind === "tag" ? "#" : "";
  const raw = node.kind === "cluster" ? `\u25a3 ${node.label}` : `${prefix}${node.label}`;
  const max = LAYOUT.maxLabelChars;
  return raw.length > max ? `${raw.slice(0, max - 1)}…` : raw;
}

function edgesHtml(list, positions, active) {
  return list.map((edge) => {
    const from = positions[edge.from];
    const to = positions[edge.to];
    if (!from || !to) return "";
    const faded = active && !(active.byId[edge.from] && active.byId[edge.to]) ? " faded" : "";
    const color = GRAPH_EDGE_COLORS[edge.source] || "#9ca3af";
    return `<line class="graph-edge graph-edge-${esc(edge.source)}${faded}" data-source="${esc(edge.source)}" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="${color}" />`;
  }).join("");
}

function focusFor(layoutView) {
  if (!view.focusId) return null;
  return focusSet(layoutView.nodes, layoutView.edges, view.focusId);
}

function renderSvg() {
  const layoutView = view.rendered;
  const active = focusFor(layoutView);
  const edges = edgesHtml(layoutView.edges, layoutView.positions, active);
  const nodes = nodesHtml(layoutView.nodes, layoutView.positions, active);
  el.graphCanvas.innerHTML =
    `<g class="graph-edges" aria-hidden="true">${edges}</g>` +
    `<g class="graph-nodes">${nodes}</g>`;
  applyViewBox();
  wireGraphNodes();
  renderStatus(active);
  renderFilterChips();
  renderClusterToggle();
  view.version += 1;
}

async function loadGraph() {
  clearViewError(el.graphZone);
  el.graphZone.classList.remove("hidden");
  el.graphEmpty.classList.add("hidden");
  el.graphScroll.classList.remove("hidden");
  el.graphCanvas.innerHTML = "";
  el.graphEmpty.querySelector("p").textContent = "暂无可导航的关系图谱。";
  try {
    const payload = await api("/api/graph");
    view.payload = payload;
    if (payload.empty) {
      el.graphEmpty.classList.remove("hidden");
      el.graphScroll.classList.add("hidden");
      renderStatus(null);
      return;
    }
    if (view.clusters === "auto" && payload.counts.documents > CLUSTER_THRESHOLD) {
      view.clusters = "collapse";
    }
    computeView();
    renderSvg();
    wireGraphInteractions();
  } catch (e) {
    el.graphEmpty.classList.add("hidden");
    el.graphScroll.classList.add("hidden");
    showViewError(el.graphZone, "加载图谱失败：" + e.message, loadGraph);
  }
}

/* ---------- status + filter chips (visible feedback for AC3) ---------- */

function setStatus(text, filtered) {
  if (!el.graphStatus) return;
  el.graphStatus.textContent = text;
  el.graphStatus.classList.toggle("filtered", Boolean(filtered));
}

function renderStatus(active) {
  const counts = view.payload && view.payload.counts;
  const shown = view.rendered ? view.rendered.nodes.length : 0;
  const total = (counts && counts.nodes) || 0;
  const pieces = [];
  pieces.push(view.subgraph && view.subgraph.nodes.length !== total
    ? `显示 ${shown} / ${total} 个节点`
    : `${total} 个节点`);
  pieces.push(`${view.rendered ? view.rendered.edges.length : 0} 条边`);
  const activeSources = ALL_SOURCES.filter((source) => view.filters.sources.has(source));
  if (activeSources.length !== ALL_SOURCES.length) {
    pieces.push(`边来源：${activeSources.map(sourceLabel).join("、") || "无"}`);
  }
  if (view.filters.collections.size) {
    pieces.push(`集合：${[...view.filters.collections].join("、")}`);
  }
  if (view.filters.tags.size) {
    pieces.push(`标签：${[...view.filters.tags].map((tag) => `#${tag}`).join("、")}`);
  }
  if (view.topic) pieces.push(`主题：${view.topic}`);
  if (active) pieces.push("聚焦邻域（点击空白恢复）");
  if (view.clusters === "collapse" && view.payload && view.payload.clusters.length) {
    const collapsed = (view.rendered.aggregates || []).length;
    pieces.push(`聚类收敛：${collapsed} 个主题聚合`);
  }
  setStatus(pieces.join(" · "), active || hasActiveFilter());
}

function sourceLabel(source) {
  return { topic: "主题", tag: "标签", manual: "手工" }[source] || source;
}

function hasActiveFilter() {
  return view.filters.sources.size !== ALL_SOURCES.length
    || view.filters.collections.size > 0
    || view.filters.tags.size > 0
    || Boolean(view.topic);
}

function renderFilterChips() {
  const filters = (view.payload && view.payload.filters) || {};
  if (el.graphSourceChips) {
    el.graphSourceChips.innerHTML = ALL_SOURCES.map((source) => {
      const on = view.filters.sources.has(source);
      const available = (filters.sources || []).includes(source);
      return `<button type="button" class="graph-chip graph-chip-${source}${on ? " active" : ""}"`
        + ` data-source="${source}" aria-pressed="${on}">${sourceLabel(source)}</button>`;
    }).join("") || '<span class="dim">暂无关系来源</span>';
  }
  if (el.graphSetChips) {
    const collections = filters.collections || [];
    el.graphSetChips.innerHTML = `<span class="graph-filter-label">集合</span>`
      + (collections.length
        ? collections.map((item) => {
          const on = view.filters.collections.has(item.id);
          return `<button type="button" class="graph-chip${on ? " active" : ""}"`
            + ` data-collection="${esc(item.id)}" aria-pressed="${on}">${esc(item.label)}`
            + ` <span class="dim">${item.count}</span></button>`;
        }).join("")
        : '<span class="dim">无</span>');
  }
  if (el.graphTagChips) {
    const tags = filters.tags || [];
    el.graphTagChips.innerHTML = `<span class="graph-filter-label">标签</span>`
      + (tags.length
        ? tags.map((item) => {
          const on = view.filters.tags.has(item.id);
          return `<button type="button" class="graph-chip${on ? " active" : ""}"`
            + ` data-tag="${esc(item.id)}" aria-pressed="${on}">#${esc(item.label)}`
            + ` <span class="dim">${item.count}</span></button>`;
        }).join("")
        : '<span class="dim">无</span>');
  }
}

/* The cluster toggle is a two-state control: the label, `.active` class and
   `aria-pressed` must all follow the rendered cluster state, otherwise the
   button gives no feedback that the mode changed (U4-4). */
function renderClusterToggle() {
  if (!el.graphClustersToggle) return;
  // Reflect what is actually on screen: `auto` only aggregates above the
  // threshold, so "expanded" means no aggregates were rendered.
  const collapsed = Boolean(view.rendered && view.rendered.aggregates
    && view.rendered.aggregates.length);
  el.graphClustersToggle.textContent = collapsed ? "聚类收敛" : "聚类展开";
  el.graphClustersToggle.classList.toggle("active", collapsed);
  el.graphClustersToggle.setAttribute("aria-pressed", String(collapsed));
}

/* ---------- interaction wiring ---------- */

function commit(next = {}) {
  Object.assign(view, next);
  // URL is the source of truth: it re-renders through the router, which keeps
  // history/back-forward and direct links consistent.
  go(stateHash());
}

function stateHash({ focus, clusters } = {}) {
  const focusId = focus === undefined ? view.focusId : focus;
  const clusterMode = clusters === undefined ? view.clusters : clusters;
  return graphHash({
    sources: ALL_SOURCES.filter((source) => view.filters.sources.has(source)),
    collections: [...view.filters.collections],
    tags: [...view.filters.tags],
    topic: view.topic,
    focus: focusId,
    clusters: clusterMode === "auto" ? null : clusterMode,
  });
}

function isBackground(target) {
  return !target.closest || !target.closest("g.graph-node");
}

/* Single activation path shared by mouse click and keyboard (Enter/Space), so
   the two input modes cannot drift apart.

   Navigation semantics (restored to pre-U4 behaviour after review):
     - documents: first activation focuses the 1-hop neighbourhood, a second
       one navigates to the editor; double-click navigates directly.
     - topics / tags / collections: activation navigates straight to the
       library filter (`go(route)`); it must not enter focus mode.
     - clusters: activation expands that aggregate inline. */
function activateNode(node) {
  const clusterId = node.dataset.cluster;
  if (clusterId) {
    if (view.clusters === "expand") return; // already fully expanded
    view.expanded.add(clusterId);
    computeView();
    renderSvg();
    return;
  }
  const id = node.dataset.nodeId;
  if (node.dataset.kind === "document") {
    if (view.focusId !== id) {
      // focus is a view-only state: no relayout, just a re-render
      view.focusId = id;
      renderSvg();
      return;
    }
    go(node.dataset.route || "#library");
    return;
  }
  if (node.dataset.route) go(node.dataset.route);
}

function wireGraphNodes() {
  el.graphCanvas.querySelectorAll("g.graph-node[data-route], g.graph-node[data-cluster]")
    .forEach((node) => {
      node.addEventListener("click", (event) => {
        event.stopPropagation();
        activateNode(node);
      });
      node.addEventListener("dblclick", (event) => {
        event.stopPropagation();
        if (node.dataset.route) go(node.dataset.route);
      });
      node.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        activateNode(node);
      });
    });
}

function wireGraphInteractions() {
  const canvas = el.graphCanvas;
  if (canvas.dataset.interactionsWired === "1") return;
  canvas.dataset.interactionsWired = "1";

  canvas.addEventListener("click", (event) => {
    if (!isBackground(event.target)) return;
    if (!view.focusId) return;
    view.focusId = null;
    renderSvg();
  });

  let dragging = null;
  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !isBackground(event.target)) return;
    // Record the raw screen position: each pointermove applies the delta from
    // the previous event, so the accumulated pan is never re-fed into the next
    // step (the old CTM-based version re-added it and accelerated quadratically).
    dragging = { lastX: event.clientX, lastY: event.clientY };
    canvas.classList.add("panning");
    if (canvas.setPointerCapture) canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const layout = currentLayout();
    const rect = canvas.getBoundingClientRect();
    const from = pointerToLayout(dragging.lastX, dragging.lastY, rect, layout, view.zoom);
    const to = pointerToLayout(event.clientX, event.clientY, rect, layout, view.zoom);
    dragging.lastX = event.clientX;
    dragging.lastY = event.clientY;
    // grab semantics: the content follows the cursor, so pan moves the other way
    view.pan = { x: view.pan.x - (to.x - from.x), y: view.pan.y - (to.y - from.y) };
    applyViewBox();
  });
  const endDrag = (event) => {
    if (!dragging) return;
    dragging = null;
    canvas.classList.remove("panning");
    if (canvas.releasePointerCapture && event && event.pointerId != null) {
      try { canvas.releasePointerCapture(event.pointerId); } catch (_) { /* ignore */ }
    }
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointerleave", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1;
    const anchor = canvasPoint(event);
    const next = zoomedViewBox(currentLayout(), view.zoom, view.pan, factor, anchor);
    view.zoom = next.zoom;
    view.pan = next.pan;
    applyViewBox();
  }, { passive: false });
}

function wireGraphControls() {
  if (el.graphZoomIn) {
    el.graphZoomIn.addEventListener("click", () => {
      const next = zoomedViewBox(currentLayout(), view.zoom, view.pan, ZOOM_STEP_RATIO);
      view.zoom = next.zoom;
      view.pan = next.pan;
      applyViewBox();
    });
  }
  if (el.graphZoomOut) {
    el.graphZoomOut.addEventListener("click", () => {
      const next = zoomedViewBox(currentLayout(), view.zoom, view.pan, 1 / ZOOM_STEP_RATIO);
      view.zoom = next.zoom;
      view.pan = next.pan;
      applyViewBox();
    });
  }
  if (el.graphFit) {
    el.graphFit.addEventListener("click", () => {
      view.zoom = 1;
      view.pan = { x: 0, y: 0 };
      applyViewBox();
    });
  }
  if (el.graphReset) {
    el.graphReset.addEventListener("click", () => {
      view.zoom = 1;
      view.pan = { x: 0, y: 0 };
      view.focusId = null;
      commit();
    });
  }
  if (el.graphClustersToggle) {
    el.graphClustersToggle.addEventListener("click", () => {
      const next = view.clusters === "expand" ? "collapse" : "expand";
      if (next === "expand") view.expanded.clear();
      commit({ clusters: next, focus: null });
    });
  }
  if (el.graphClearFilters) {
    el.graphClearFilters.addEventListener("click", () => {
      view.filters.sources = new Set(ALL_SOURCES);
      view.filters.collections = new Set();
      view.filters.tags = new Set();
      view.topic = null;
      commit();
    });
  }
  if (el.graphFilterZone) {
    el.graphFilterZone.addEventListener("click", (event) => {
      const button = event.target.closest("button.graph-chip");
      if (!button) return;
      if (button.dataset.source) {
        const source = button.dataset.source;
        const next = new Set(view.filters.sources);
        if (next.has(source)) next.delete(source);
        else next.add(source);
        if (!next.size) return; // never hide every edge silently
        view.filters.sources = next;
        commit({ focus: null });
      } else if (button.dataset.collection) {
        const id = button.dataset.collection;
        const next = new Set(view.filters.collections);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        view.filters.collections = next;
        commit({ focus: null });
      } else if (button.dataset.tag) {
        const tag = button.dataset.tag;
        const next = new Set(view.filters.tags);
        if (next.has(tag)) next.delete(tag);
        else next.add(tag);
        view.filters.tags = next;
        commit({ focus: null });
      }
    });
  }
}

/* ---------- view entry ---------- */

function readRoute(route) {
  view.filters.sources = new Set(route.sources && route.sources.length
    ? route.sources.filter((source) => ALL_SOURCES.includes(source))
    : ALL_SOURCES);
  if (!view.filters.sources.size) view.filters.sources = new Set(ALL_SOURCES);
  view.filters.collections = new Set(route.collections || []);
  view.filters.tags = new Set(route.tags || []);
  view.topic = route.topic || null;
  view.focusId = route.focus || null;
  view.expanded = new Set();
  view.clusters = route.clusters || "auto";
  view.zoom = 1;
  view.pan = { x: 0, y: 0 };
}

export async function renderGraphRoute(route = { name: "graph" }) {
  if (route.name === "graph") readRoute(route);
  await loadGraph();
}

/* Small automation/QA seam (no behaviour of its own): lets the offline visual
   probe read the current view state and observe when a render has settled
   instead of racing the async payload.  Kept read-only except `version`, which
   the render pipeline bumps. */
window.__g2nGraph = {
  get version() { return view.version; },
  get zoom() { return view.zoom; },
  get pan() { return { ...view.pan }; },
  get focusId() { return view.focusId; },
  get clusters() { return view.clusters; },
  get counts() {
    return view.rendered
      ? { nodes: view.rendered.nodes.length, edges: view.rendered.edges.length }
      : { nodes: 0, edges: 0 };
  },
  get sources() { return [...view.filters.sources]; },
  get tags() { return [...view.filters.tags]; },
  get collections() { return [...view.filters.collections]; },
  get layout() {
    const layout = (view.rendered && view.rendered.layout) || view.layout;
    return layout ? { width: layout.width, height: layout.height } : null;
  },
};

wireGraphControls();
registerView("graph", renderGraphRoute);
