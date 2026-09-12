// Node contract test for the U4 knowledge-graph layout engine + view model.
//
// `graph-layout.js` is pure (no DOM, no network), so it runs under plain Node.
// The "no node bounding-box overlap" acceptance criterion is asserted here as a
// programmatic property, and the Python suite (`tests/test_graph_layout.py`)
// re-runs this script and parses the JSON summary below.
// Run: node tests/graph_layout.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const layoutPath = path.join(here, "..", "graph2note", "webstatic", "js", "views", "graph-layout.js");
const L = await import(pathToFileURL(layoutPath).href);

const summary = { checks: {}, counts: {}, metrics: {} };
function check(name, fn) {
  fn();
  summary.checks[name] = true;
}
const round = (value) => Math.round(value * 100) / 100;

// ---- fixture: >=30 documents, multiple topics/tags, three edge sources -----
// Shape matches /api/graph: theme topics/tags form the bulk, one manual
// collection and a couple of manual document relations add the third source.
const TOPICS = ["数学", "物理", "化学", "生物", "历史", "文学", "工程", "艺术"];
const TAGS = ["重点", "草稿", "待整理", "复习", "参考", "归档", "疑问"];
const DOC_COUNT = 36;

function buildPayload() {
  const nodes = [];
  const edges = [];
  const clusters = new Map();
  const tagCounts = new Map();
  const addNode = (node) => nodes.push(node);
  for (let i = 0; i < DOC_COUNT; i += 1) {
    const id = `d${String(i).padStart(2, "0")}`;
    const topic = TOPICS[i % TOPICS.length];
    const tag = TAGS[i % TAGS.length];
    addNode({
      id: `document:${id}`, kind: "document", label: `文档 ${i}`, route: `#doc/${id}`,
      document_id: id, degree: 0, isolated: false,
    });
    if (!nodes.some((n) => n.id === `topic:${topic}`)) {
      addNode({ id: `topic:${topic}`, kind: "topic", label: topic, route: `#library/topic/${encodeURIComponent(topic)}`, topic, degree: 0, isolated: false });
    }
    if (!nodes.some((n) => n.id === `tag:${tag}`)) {
      addNode({ id: `tag:${tag}`, kind: "tag", label: tag, route: `#library/tag/${encodeURIComponent(tag)}`, tag, degree: 0, isolated: false });
    }
    edges.push({
      id: `topic:document:${id}->topic:${topic}`, from: `document:${id}`, to: `topic:${topic}`,
      source: "topic", document_id: id, topic,
    });
    edges.push({
      id: `tag:document:${id}->tag:${tag}`, from: `document:${id}`, to: `tag:${tag}`,
      source: "tag", document_id: id, tag,
    });
    if (!clusters.has(topic)) clusters.set(topic, []);
    clusters.get(topic).push(id);
    tagCounts.set(tag, (tagCounts.get(tag) || 0) + 1);
  }
  // manual source: one collection with three members + one document relation
  const manualMembers = ["d00", "d01", "d02"];
  addNode({ id: "collection:c1", kind: "collection", label: "研究", route: "#library/collection/c1", collection_id: "c1", degree: 0, isolated: false });
  for (const member of manualMembers) {
    edges.push({
      id: `manual:document:${member}->collection:c1`, from: `document:${member}`, to: "collection:c1",
      source: "manual", document_id: member, collection_id: "c1", collection: "研究",
    });
  }
  edges.push({
    id: "manual:document:d03->document:d04", from: "document:d03", to: "document:d04",
    source: "manual", document_id: "d03", target_id: "document:d04",
  });
  // lone document: must stay visible and never overlap either
  addNode({ id: "document:solo", kind: "document", label: "孤立文档", route: "#doc/solo", document_id: "solo", degree: 0, isolated: true });
  clusters.set("__solo__", ["solo"]);

  const degrees = new Map();
  for (const edge of edges) {
    degrees.set(edge.from, (degrees.get(edge.from) || 0) + 1);
    degrees.set(edge.to, (degrees.get(edge.to) || 0) + 1);
  }
  for (const node of nodes) {
    node.degree = degrees.get(node.id) || 0;
    node.isolated = node.degree === 0;
  }
  return {
    nodes,
    edges,
    sources: ["topic", "tag", "manual"],
    empty: false,
    counts: {
      nodes: nodes.length, edges: edges.length, documents: DOC_COUNT + 1,
      topics: TOPICS.length, tags: TAGS.length, collections: 1,
    },
    clusters: [...clusters.entries()].map(([topic, documents]) => ({
      id: `cluster:topic:${topic}`,
      topic: topic === "__solo__" ? null : topic,
      label: topic === "__solo__" ? "未归类" : topic,
      route: "#library",
      documents,
      size: documents.length,
      unclustered: topic === "__solo__",
    })),
    filters: {
      sources: ["topic", "tag", "manual"],
      collections: [{ id: "c1", label: "研究", count: 3, route: "#library/collection/c1" }],
      tags: [...tagCounts.entries()].map(([tag, count]) => ({ id: tag, label: tag, count, route: "#library/tag/x" })),
    },
  };
}

const payload = buildPayload();
assert.ok(payload.counts.documents >= 30, "fixture needs >=30 documents");
assert.strictEqual(payload.sources.length, 3, "fixture needs all three edge sources");
summary.counts = { nodes: payload.counts.nodes, edges: payload.counts.edges, documents: payload.counts.documents };

// ---- 1) AC1: zero node bounding-box overlap, expanded view ---------------
const layout = L.computeLayout(payload.nodes, payload.edges, { seed: 7 });
check("overlap_zero_expanded", () => {
  const pairs = L.findOverlaps(layout.nodes, layout.positions);
  assert.deepStrictEqual(pairs.slice(0, 5), [], `overlapping node boxes: ${JSON.stringify(pairs.slice(0, 5))}`);
  assert.strictEqual(L.overlapCount(layout.nodes, layout.positions), 0);
});
summary.counts.expandedNodes = layout.nodes.length;
summary.metrics.expanded = {
  viewBoxWidth: round(layout.width),
  viewBoxHeight: round(layout.height),
  minEdgeLength: round(Math.min(...payload.edges.map((edge) => Math.hypot(
    layout.positions[edge.from].x - layout.positions[edge.to].x,
    layout.positions[edge.from].y - layout.positions[edge.to].y,
  )))),
  overlapPairs: L.overlapCount(layout.nodes, layout.positions),
};

// ---- 2) deterministic for a given seed, even with reversed input order ----
check("deterministic_layout", () => {
  const reversed = L.computeLayout(
    [...payload.nodes].reverse(), [...payload.edges].reverse(), { seed: 7 },
  );
  assert.deepStrictEqual(reversed.positions, layout.positions);
  assert.strictEqual(reversed.width, layout.width);
  assert.strictEqual(reversed.height, layout.height);
});

// ---- 3) AC3: cluster convergence also renders overlap-free ---------------
check("overlap_zero_collapsed", () => {
  const collapsed = L.applyClusters(
    { nodes: layout.nodes, edges: layout.edges }, payload, layout.positions, true, new Set(),
  );
  const clusterNodes = collapsed.nodes.filter((node) => node.kind === "cluster");
  assert.ok(clusterNodes.length >= 2, "expected >=2 topic aggregates");
  assert.ok(collapsed.nodes.length < layout.nodes.length, "convergence must hide documents");
  // graph.js re-separates the aggregate centroids; assert that exact path
  const relayout = L.solveFromPositions(
    collapsed.nodes, collapsed.edges, { ...layout.positions, ...collapsed.clusterPositions },
  );
  assert.strictEqual(L.overlapCount(relayout.nodes, relayout.positions), 0);
  summary.counts.collapsedNodes = collapsed.nodes.length;
  summary.counts.aggregates = clusterNodes.length;
  summary.metrics.collapsed = {
    overlapPairs: L.overlapCount(relayout.nodes, relayout.positions),
    viewBoxWidth: round(relayout.width),
    viewBoxHeight: round(relayout.height),
  };
});

check("cluster_expand_reverts_to_documents", () => {
  const first = payload.clusters[0];
  const expanded = L.applyClusters(
    { nodes: layout.nodes, edges: layout.edges }, payload, layout.positions, true, new Set([first.id]),
  );
  assert.ok(expanded.nodes.some((node) => node.id === `document:${first.documents[0]}`));
  assert.ok(!expanded.aggregates.some((node) => node.id === first.id));
});

// ---- 4) AC2: zoom covers 0.25x-4x and keeps every node -------------------
check("zoom_range_and_nodes_preserved", () => {
  assert.strictEqual(L.clampZoom(0.01), 0.25);
  assert.strictEqual(L.clampZoom(99), 4);
  assert.strictEqual(L.MIN_ZOOM, 0.25);
  assert.strictEqual(L.MAX_ZOOM, 4);
  const wide = L.viewBoxFor(layout, 0.25);
  const tight = L.viewBoxFor(layout, 4);
  assert.ok(Math.abs(wide.width - layout.width * 4) < 1e-9);
  assert.ok(Math.abs(tight.width - layout.width / 4) < 1e-9);
  // zooming + panning never drops a node: positions are independent of the view
  for (const zoom of [0.25, 0.5, 1, 2, 4]) {
    const box = L.viewBoxFor(layout, zoom);
    assert.ok(box.width > 0 && box.height > 0);
    const ids = new Set(Object.keys(layout.positions));
    assert.strictEqual(ids.size, layout.nodes.length);
  }
});

check("zoom_anchor_is_stable", () => {
  // The cursor must stay over the same layout point: its fractional position in
  // the *panned* viewBox is invariant across a zoom step.
  const anchor = { x: 400, y: 300 };
  const panned = (zoom, pan) => {
    const box = L.viewBoxFor(layout, zoom);
    return { x: pan.x, y: pan.y, width: box.width, height: box.height };
  };
  const ratio = (box) => ({
    x: (anchor.x - box.x) / box.width,
    y: (anchor.y - box.y) / box.height,
  });
  const before = ratio(panned(1, { x: 0, y: 0 }));
  const zoomed = L.zoomedViewBox(layout, 1, { x: 0, y: 0 }, 2, anchor);
  const after = ratio(panned(zoomed.zoom, zoomed.pan));
  assert.ok(Math.abs(before.x - after.x) < 1e-9, `anchor x drifted: ${before.x} -> ${after.x}`);
  assert.ok(Math.abs(before.y - after.y) < 1e-9, `anchor y drifted: ${before.y} -> ${after.y}`);
});

check("pan_translates_viewbox", () => {
  const layoutWidth = 1000;
  const fake = { width: layoutWidth, height: 800 };
  const panned = L.panBy(fake, 1, { x: 0, y: 0 }, 0.1, -0.05);
  assert.ok(Math.abs(panned.pan.x - layoutWidth * 0.1) < 1e-9);
  assert.ok(Math.abs(panned.pan.y + 800 * 0.05) < 1e-9);
});

// ---- 5) focus neighbourhood -------------------------------------------------
check("focus_one_hop", () => {
  const focus = L.focusSet(layout.nodes, layout.edges, "document:d00");
  assert.ok(focus, "known node must focus");
  const neighbours = new Set(["document:d00"]);
  for (const edge of layout.edges) {
    if (edge.from === "document:d00") neighbours.add(edge.to);
    else if (edge.to === "document:d00") neighbours.add(edge.from);
  }
  assert.deepStrictEqual([...focus.activeNodes].sort(), [...neighbours].sort());
  assert.ok(focus.activeNodes.size < layout.nodes.length, "focus must dim the rest");
  assert.strictEqual(focus.byId["topic:数学"], true);
  assert.strictEqual(focus.byId["document:d30"], false);
  assert.strictEqual(L.focusSet(layout.nodes, layout.edges, "document:missing"), null);
});

// ---- 6) source / collection / tag filtering --------------------------------
check("source_filter_keeps_only_matching_edges", () => {
  const allTagEdges = payload.edges.filter((edge) => edge.source === "tag");
  const tagsOnly = L.subgraph(payload, { sources: new Set(["tag"]) });
  assert.strictEqual(tagsOnly.edges.length, allTagEdges.length);
  assert.ok(tagsOnly.edges.every((edge) => edge.source === "tag"));
  assert.ok(!tagsOnly.nodes.some((node) => node.kind === "collection"), "manual collection hidden");
  assert.ok(!tagsOnly.nodes.some((node) => node.kind === "topic"), "topic nodes hidden");
  assert.ok(tagsOnly.nodes.some((node) => node.kind === "document"));
  assert.ok(tagsOnly.nodes.some((node) => node.kind === "tag"));

  const manualOnly = L.subgraph(payload, { sources: new Set(["manual"]) });
  assert.ok(manualOnly.edges.every((edge) => edge.source === "manual"));
  assert.ok(manualOnly.nodes.some((node) => node.id === "collection:c1"));
  assert.ok(!manualOnly.nodes.some((node) => node.kind === "topic"), "topic edges hidden");

  const topicOnly = L.subgraph(payload, { sources: new Set(["topic"]) });
  assert.ok(topicOnly.edges.every((edge) => edge.source === "topic"));
  assert.ok(topicOnly.nodes.some((node) => node.kind === "topic"));
  assert.ok(!topicOnly.nodes.some((node) => node.kind === "tag"), "tag edges hidden");
});

check("collection_and_tag_filter_narrow_documents", () => {
  const inCollection = L.subgraph(payload, { collections: new Set(["c1"]) });
  const collectionDocs = inCollection.nodes.filter((node) => node.kind === "document");
  assert.deepStrictEqual(collectionDocs.map((node) => node.document_id).sort(), ["d00", "d01", "d02"]);

  const tagFiltered = L.subgraph(payload, { tags: new Set(["重点"]) });
  const expectedTags = [];
  for (let i = 0; i < DOC_COUNT; i += 1) if (TAGS[i % TAGS.length] === "重点") expectedTags.push(`d${String(i).padStart(2, "0")}`);
  assert.deepStrictEqual(tagFiltered.nodes.filter((node) => node.kind === "document").map((node) => node.document_id).sort(), [...expectedTags].sort());
  assert.strictEqual(tagFiltered.nodes.filter((node) => node.kind === "tag").length, 1);

  const both = L.subgraph(payload, { collections: new Set(["c1"]), tags: new Set(["重点"]) });
  assert.ok(both.nodes.filter((node) => node.kind === "document").every((node) => ["d00", "d01", "d02"].includes(node.document_id)));

  const topicView = L.subgraph(payload, { topic: "数学" });
  assert.ok(topicView.nodes.filter((node) => node.kind === "document").length > 0);
  assert.ok(topicView.nodes.filter((node) => node.kind === "topic").every((node) => node.topic === "数学"));
});

// ---- 7) rendered labels stay inside the node box ---------------------------
check("labels_are_truncated_to_fit", () => {
  const long = { kind: "tag", label: "这是一个非常长的标签名称" };
  const width = L.labelWidth(long);
  assert.ok(width <= 2 * L.nodeRadius(long) + L.LAYOUT.labelCharWidth);
  assert.ok(L.LAYOUT.labelCharWidth > 0);
});

// ---- summary for the Python wrapper ---------------------------------------
console.log(JSON.stringify(summary, null, 2));
