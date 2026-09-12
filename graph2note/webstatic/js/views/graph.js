/* graph2note — read-only, provenance-aware relationship graph (U1 relocation). */
"use strict";

import { el } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { go, registerView } from "../router.js";
import { showToast } from "../ui.js";

const GRAPH_EDGE_COLORS = { topic: "#4f7fe8", tag: "#c07a1a", manual: "#16836d" };
const GRAPH_KIND_LABELS = { document: "文档", topic: "主题", tag: "标签", collection: "集合" };

function graphLayout(nodes) {
  const width = 1000;
  const columns = { document: 150, topic: 390, tag: 630, collection: 870 };
  const groups = {};
  for (const node of nodes) (groups[node.kind] ||= []).push(node);
  const maxCount = Math.max(1, ...Object.values(groups).map((items) => items.length));
  const height = Math.max(430, maxCount * 76 + 80);
  const positions = {};
  for (const [kind, items] of Object.entries(groups)) {
    const step = height / (items.length + 1);
    items.forEach((node, index) => {
      positions[node.id] = { x: columns[kind] || 150, y: step * (index + 1) };
    });
  }
  return { width, height, positions };
}

function graphNodeText(node) {
  const prefix = node.kind === "tag" ? "#" : "";
  return `${prefix}${node.label}`;
}

function wireGraphNodes() {
  el.graphCanvas.querySelectorAll("g.graph-node[data-route]").forEach((node) => {
    const open = () => go(node.dataset.route);
    node.addEventListener("click", open);
    node.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault(); open();
      }
    });
  });
}

function renderGraphSvg(payload) {
  const { width, height, positions } = graphLayout(payload.nodes || []);
  const lines = (payload.edges || []).map((edge) => {
    const from = positions[edge.from];
    const to = positions[edge.to];
    if (!from || !to) return "";
    const color = GRAPH_EDGE_COLORS[edge.source] || "#9ca3af";
    return `<line class="graph-edge graph-edge-${esc(edge.source)}" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="${color}" />`;
  }).join("");
  const nodes = (payload.nodes || []).map((node) => {
    const point = positions[node.id];
    const label = graphNodeText(node);
    const escaped = esc(label);
    return `<g class="graph-node graph-node-${esc(node.kind)}${node.isolated ? " isolated" : ""}" data-route="${esc(node.route)}" data-node-id="${esc(node.id)}" role="button" tabindex="0" transform="translate(${point.x} ${point.y})">
      <title>${escaped} · ${esc(GRAPH_KIND_LABELS[node.kind] || node.kind)} · ${node.degree} 条关系</title>
      <circle r="${node.kind === "document" ? 26 : 22}"></circle>
      <text text-anchor="middle" dy="4">${escaped.length > 18 ? `${esc(label.slice(0, 17))}…` : escaped}</text>
    </g>`;
  }).join("");
  el.graphCanvas.setAttribute("viewBox", `0 0 ${width} ${height}`);
  el.graphCanvas.innerHTML = `<g class="graph-edges">${lines}</g><g class="graph-nodes">${nodes}</g>`;
  wireGraphNodes();
}

async function renderGraph() {
  el.graphZone.classList.remove("hidden");
  el.graphEmpty.classList.add("hidden");
  el.graphScroll.classList.remove("hidden");
  el.graphCanvas.innerHTML = "";
  el.graphEmpty.querySelector("p").textContent = "暂无可导航的关系图谱。";
  try {
    const graph = await api("/api/graph");
    if (graph.empty) {
      el.graphEmpty.classList.remove("hidden");
      el.graphScroll.classList.add("hidden");
      return;
    }
    renderGraphSvg(graph);
  } catch (e) {
    el.graphEmpty.querySelector("p").textContent = "图谱加载失败。";
    el.graphEmpty.classList.remove("hidden");
    el.graphScroll.classList.add("hidden");
    showToast("加载图谱失败：" + e.message, "err");
  }
}

registerView("graph", renderGraph);
