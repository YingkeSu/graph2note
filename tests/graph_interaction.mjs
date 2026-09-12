// Offline DOM contract for the U4 knowledge-graph *interaction* fixes.
//
// This drives the real `views/graph.js` module (no browser, no network) under a
// tiny DOM shim and asserts the two regressions the review caught:
//
//   U4-1  drag-pan must be linear in the number of pointermove events.  The old
//         code re-derived the pointer position through the already-panned CTM
//         every event, so the accumulated pan was fed back in and the motion
//         accelerated quadratically.  The original evidence dispatched a single
//         pointermove and could not see it.
//   U4-2  a single click on a topic/tag/collection node must navigate to its
//         library route (pre-U4 behaviour); only document nodes enter the
//         focus state on single click.
//
// Usage: node tests/graph_interaction.mjs < payload.json
// ``payload.json`` is the exact ``/api/graph`` projection (produced by
// ``graph2note.graph.build_graph`` in tests/test_graph_interaction.py), so the
// harness renders the same shape the app receives.  Prints a JSON summary.
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webstatic = path.join(here, "..", "graph2note", "webstatic");

/* ---------- minimal DOM shim (only what graph.js and its imports touch) ---- */

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const ATTR_RE = /([a-zA-Z-]+)="([^"]*)"/g;

class FakeElement {
  constructor(tag = "div", id = "") {
    this.tag = tag;
    this.id = id;
    this.isCanvas = false;
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.disabled = false;
    this._listeners = new Map();
    this._attrs = new Map();
    this._classes = new Set();
    this._text = "";
    this._html = "";
    this._htmlSet = false;
    this._nodes = [];
    this._children = new Map();
    this._rect = { left: 0, top: 0, width: 320, height: 240 };
    this.classList = {
      add: (...names) => names.forEach((name) => this._classes.add(name)),
      remove: (...names) => names.forEach((name) => this._classes.delete(name)),
      contains: (name) => this._classes.has(name),
      toggle: (name, force) => {
        const on = force === undefined ? !this._classes.has(name) : Boolean(force);
        if (on) this._classes.add(name);
        else this._classes.delete(name);
        return on;
      },
    };
  }

  get className() { return [...this._classes].join(" "); }
  set className(value) {
    this._classes = new Set(String(value).split(/\s+/).filter(Boolean));
  }

  get textContent() { return this._text; }
  set textContent(value) {
    this._text = String(value == null ? "" : value);
    if (!this._htmlSet) this._html = escapeHtml(this._text);
  }

  get innerHTML() { return this._html; }
  set innerHTML(value) {
    this._htmlSet = true;
    this._html = String(value == null ? "" : value);
    this._nodes = this.isCanvas ? this._parseNodes(this._html) : [];
  }

  _parseNodes(html) {
    const nodes = [];
    const tags = /<g\s+([^>]*?)>/g;
    let tag;
    while ((tag = tags.exec(html)) !== null) {
      const attrs = tag[1];
      if (!/class="[^"]*graph-node[^"]*"/.test(attrs)) continue;
      const map = {};
      let attr;
      ATTR_RE.lastIndex = 0;
      while ((attr = ATTR_RE.exec(attrs)) !== null) map[attr[1]] = attr[2];
      const element = new FakeElement("g");
      element.dataset.nodeId = map["data-node-id"];
      element.dataset.kind = map["data-kind"];
      if (map["data-route"] !== undefined) element.dataset.route = map["data-route"];
      if (map["data-cluster"] !== undefined) element.dataset.cluster = map["data-cluster"];
      element._attrs = new Map(Object.entries(map));
      nodes.push(element);
    }
    return nodes;
  }

  addEventListener(type, handler) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(handler);
  }

  removeEventListener() { /* shim */ }

  trigger(type, event = {}) {
    for (const handler of this._listeners.get(type) || []) handler(event);
  }

  setAttribute(name, value) { this._attrs.set(name, String(value)); }
  getAttribute(name) { return this._attrs.has(name) ? this._attrs.get(name) : null; }
  removeAttribute(name) { this._attrs.delete(name); }

  querySelector(selector) {
    // This success-path fixture has no loading-error banner.
    if (selector === ".view-error") return null;
    if (!this._children.has(selector)) this._children.set(selector, new FakeElement());
    return this._children.get(selector);
  }

  querySelectorAll(selector) {
    if (!this.isCanvas) return [];
    if (selector.includes("graph-node")) {
      return this._nodes.filter((node) => node.dataset.route || node.dataset.cluster);
    }
    return [];
  }

  closest() { return null; }

  /* Enough of the SVG geometry API for the legacy CTM-based pan code path so
     the regression test can actually reproduce the quadratic feedback loop the
     old implementation had.  The new delta-based code never calls this. */
  getScreenCTM() {
    const element = this;
    const raw = element._attrs.get("viewBox");
    const rect = element._rect;
    const [viewX, viewY, viewW, viewH] = raw
      ? raw.split(/\s+/).map(Number)
      : [0, 0, rect.width, rect.height];
    const scale = Math.min(rect.width / viewW, rect.height / viewH) || 1;
    const offsetX = (rect.width - viewW * scale) / 2;
    const offsetY = (rect.height - viewH * scale) / 2;
    const tx = offsetX - viewX * scale;
    const ty = offsetY - viewY * scale;
    return {
      inverse: () => ({
        matrixTransform: (point) => ({
          x: (point.x - tx) / scale,
          y: (point.y - ty) / scale,
        }),
      }),
    };
  }

  createSVGPoint() {
    return {
      x: 0,
      y: 0,
      matrixTransform(matrix) { return matrix.matrixTransform(this); },
    };
  }

  getBoundingClientRect() { return this._rect; }
  focus() { /* shim */ }
  blur() { /* shim */ }
}

const elements = new Map();
function elementFor(selector) {
  if (!elements.has(selector)) {
    const id = selector.startsWith("#") ? selector.slice(1) : "";
    const element = new FakeElement(selector === "#graph-canvas" ? "svg" : "div", id);
    if (selector === "#graph-canvas") element.isCanvas = true;
    elements.set(selector, element);
  }
  return elements.get(selector);
}

globalThis.window = globalThis;
globalThis.location = { hash: "#graph" };
globalThis.document = {
  querySelector: (selector) => elementFor(selector),
  querySelectorAll: () => [],
  createElement: (tag) => new FakeElement(tag),
  addEventListener() { /* shim */ },
  removeEventListener() { /* shim */ },
  activeElement: null,
};

let payload = null;
globalThis.fetch = async () => ({
  ok: true,
  status: 200,
  statusText: "OK",
  headers: { get: (name) => (String(name).toLowerCase() === "content-type" ? "application/json" : "") },
  json: async () => payload,
});

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => { data += chunk; });
    process.stdin.on("end", () => resolve(data));
  });
}

/* ---------- import the real view after the shim exists --------------------- */

payload = JSON.parse(await readStdin());
assert.ok(payload && Array.isArray(payload.nodes), "payload must be the /api/graph projection");

const graph = await import(pathToFileURL(path.join(webstatic, "js", "views", "graph.js")).href);
const seam = globalThis.window.__g2nGraph;
assert.ok(seam, "graph.js must expose the __g2nGraph automation seam");

const canvas = () => globalThis.document.querySelector("#graph-canvas");
const toggle = () => globalThis.document.querySelector("#graph-clusters-toggle");
const ZOOM_STEP_RATIO = 2 ** (1 / 10);

const summary = { checks: {}, details: {} };
async function check(name, fn) {
  const detail = await fn();
  summary.checks[name] = true;
  if (detail !== undefined) summary.details[name] = detail;
}
const round = (value) => Math.round(value * 1e6) / 1e6;

async function render(route) {
  globalThis.location.hash = "#graph";
  await graph.renderGraphRoute({ name: "graph", ...route });
  return canvas();
}

function click(node) {
  node.trigger("click", { stopPropagation() { /* handled */ }, target: node });
}

/* ---------- U4-1: multi-event drag pan is linear, not quadratic ------------ */

await check("drag_pan_is_linear_across_many_pointermoves", async () => {
  await render({ clusters: "expand" });
  const element = canvas();
  const layout = seam.layout;
  // rect == viewBox at zoom 1, so screen pixels map 1:1 onto layout units.
  element._rect = { left: 0, top: 0, width: layout.width, height: layout.height };

  const steps = 6;
  const dx = 20;
  const dy = 10;
  const startX = 100;
  const startY = 100;
  element.trigger("pointerdown", {
    button: 0, target: element, clientX: startX, clientY: startY, pointerId: 1,
  });

  const panX = [];
  const panY = [];
  for (let i = 1; i <= steps; i += 1) {
    element.trigger("pointermove", {
      clientX: startX + i * dx, clientY: startY + i * dy, pointerId: 1,
    });
    panX.push(seam.pan.x);
    panY.push(seam.pan.y);
  }
  element.trigger("pointerup", { pointerId: 1 });

  // every step must contribute the same, bounded delta (a quadratic feedback
  // loop would make step i grow with i).
  for (let i = 0; i < steps; i += 1) {
    const expected = -dx * (i + 1);
    assert.ok(
      Math.abs(panX[i] - expected) < 1e-6,
      `pan.x after step ${i + 1} was ${panX[i]}, expected ${expected}`,
    );
    assert.ok(Math.abs(panY[i] - (-dy * (i + 1))) < 1e-6, `pan.y step ${i + 1}: ${panY[i]}`);
  }
  // grab semantics: dragging right/down moves the content with the cursor, so
  // the viewBox pan goes the other way.
  assert.ok(panX[steps - 1] < 0 && panY[steps - 1] < 0, "content must follow the pointer");

  return {
    steps,
    inputs: { dx, dy },
    panX,
    panY,
    stepIncrement: { x: round(panX[1] - panX[0]), y: round(panY[1] - panY[0]) },
    total: { x: round(panX[steps - 1]), y: round(panY[steps - 1]) },
  };
});

/* ---------- U4-2: single-click navigation per node kind -------------------- */

await check("document_click_focuses_then_navigates", async () => {
  await render({ clusters: "expand" });
  let element = canvas();
  const first = element._nodes.find((node) => node.dataset.kind === "document");
  assert.ok(first, "a document node must be rendered");

  click(first);
  assert.strictEqual(seam.focusId, first.dataset.nodeId, "single click must focus the document");
  assert.strictEqual(globalThis.location.hash, "#graph", "focus must not navigate");

  element = canvas();
  const again = element._nodes.find((node) => node.dataset.nodeId === first.dataset.nodeId);
  click(again);
  assert.strictEqual(
    globalThis.location.hash, first.dataset.route,
    "a second click must navigate to the document editor",
  );
  return { focusId: first.dataset.nodeId, route: first.dataset.route };
});

await check("topic_and_tag_click_navigate_directly", async () => {
  const seen = {};
  for (const kind of ["topic", "tag", "collection"]) {
    await render({ clusters: "expand" });
    const element = canvas();
    const node = element._nodes.find((item) => item.dataset.kind === kind);
    assert.ok(node, `${kind} node must be rendered`);
    click(node);
    assert.strictEqual(seam.focusId, null, `${kind} single click must not enter focus`);
    assert.strictEqual(
      globalThis.location.hash, node.dataset.route,
      `${kind} single click must navigate to ${node.dataset.route}`,
    );
    seen[kind] = { nodeId: node.dataset.nodeId, route: node.dataset.route, focusId: seam.focusId };
  }
  return seen;
});

/* ---------- U4-3 / U4-4 / U4-5: cluster activation, feedback, tooltip ------ */

await check("cluster_keyboard_expand_and_toggle_feedback", async () => {
  await render({ clusters: "collapse" });
  let element = canvas();
  assert.ok(
    element.innerHTML.includes("单击展开"),
    "cluster tooltip must describe the single-click behaviour",
  );
  const cluster = element._nodes.find((node) => node.dataset.cluster);
  assert.ok(cluster, "collapsed view must render cluster nodes");
  const before = seam.counts.nodes;
  cluster.trigger("keydown", { key: "Enter", preventDefault() { /* handled */ }, target: cluster });
  const after = seam.counts.nodes;
  assert.ok(after > before, `Enter on a cluster must expand it (${before} -> ${after})`);

  const button = toggle();
  assert.strictEqual(button.textContent, "聚类收敛", "collapsed mode label");
  assert.ok(button.classList.contains("active"), "collapsed mode must be .active");
  assert.strictEqual(button.getAttribute("aria-pressed"), "true");

  await render({ clusters: "expand" });
  assert.strictEqual(button.textContent, "聚类展开", "expanded mode label");
  assert.ok(!button.classList.contains("active"), "expanded mode must drop .active");
  assert.strictEqual(button.getAttribute("aria-pressed"), "false");
  return { before, after, collapsedLabel: "聚类收敛", expandedLabel: "聚类展开" };
});

/* ---------- U4-6: zoom uses the rendered (re-solved) cluster layout -------- */

await check("zoom_button_anchor_uses_rendered_layout", async () => {
  await render({ clusters: "expand" });
  const expandedLayout = seam.layout;
  await render({ clusters: "collapse" });
  const collapsedLayout = seam.layout;
  assert.ok(
    collapsedLayout.width !== expandedLayout.width || collapsedLayout.height !== expandedLayout.height,
    "the test only discriminates if the rendered cluster layout differs from the pre-cluster one",
  );

  globalThis.document.querySelector("#graph-zoom-in").trigger("click", {});
  const zoom = seam.zoom;
  assert.ok(zoom > 1, "zoom-in must increase the zoom factor");
  const expectedX = 0.5 * collapsedLayout.width * (1 - 1 / zoom);
  const expectedY = 0.5 * collapsedLayout.height * (1 - 1 / zoom);
  assert.ok(
    Math.abs(seam.pan.x - expectedX) < 1e-6,
    `zoom anchor must use the rendered layout width: pan.x=${seam.pan.x} expected=${expectedX}`,
  );
  assert.ok(
    Math.abs(seam.pan.y - expectedY) < 1e-6,
    `zoom anchor must use the rendered layout height: pan.y=${seam.pan.y} expected=${expectedY}`,
  );
  return {
    zoom: round(zoom),
    expanded: { width: round(expandedLayout.width), height: round(expandedLayout.height) },
    collapsed: { width: round(collapsedLayout.width), height: round(collapsedLayout.height) },
    pan: { x: round(seam.pan.x), y: round(seam.pan.y) },
  };
});

console.log(JSON.stringify(summary, null, 2));
