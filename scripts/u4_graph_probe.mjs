// CDP probe for the U4 graph evidence capture.  Run with:
//   node scripts/u4_graph_probe.mjs <chrome-bin> <url> <out.png> <out.json>
// Launches the page in a visible Chrome window, waits for the async graph
// payload/render (via the `window.__g2nGraph` automation seam), measures the
// rendered graph (node bounding boxes, overlap count, zoom range, focus DOM
// state, filter results), captures a screenshot and writes a JSON metrics file.
import fs from "node:fs";
import { spawn } from "node:child_process";

const [chromeBin, url, outPng, outJson] = process.argv.slice(2);
if (!chromeBin || !url || !outPng || !outJson) {
  console.error("usage: node u4_graph_probe.mjs <chrome> <url> <out.png> <out.json>");
  process.exit(2);
}

const DEBUG_URL = "http://127.0.0.1:9333";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForTarget() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const res = await fetch(`${DEBUG_URL}/json/list`);
      const targets = await res.json();
      const page = targets.find((t) => t.type === "page" && t.url.startsWith(url.slice(0, 24)));
      if (page && page.webSocketDebuggerUrl) return page;
    } catch (_) { /* devtools not up yet */ }
    await sleep(500);
  }
  throw new Error("Chrome DevTools target did not appear");
}

class CDP {
  constructor(socketUrl) {
    this.socket = new WebSocket(socketUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.ready = new Promise((resolve, reject) => {
      this.socket.addEventListener("open", resolve);
      this.socket.addEventListener("error", reject);
    });
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(JSON.stringify(message.error)));
        else resolve(message.result);
      }
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression, returnByValue: true, awaitPromise: true,
    });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }

  close() { this.socket.close(); }
}

/* Measure the rendered graph.  Node boxes come from each <g>'s union bounding
   box in *screen* pixels (this is what a user sees), and every label is also
   checked against the box the layout engine reserved for it. */
const measureExpression = `(() => {
  const canvas = document.getElementById("graph-canvas");
  if (!canvas) return { error: "no canvas" };
  const base = canvas.getBoundingClientRect();
  const ctm = canvas.getScreenCTM();
  const nodes = [...canvas.querySelectorAll("g.graph-node")].map((node) => {
    const box = node.getBoundingClientRect();
    const text = node.querySelector("text");
    const textBox = text ? text.getBBox() : null;
    return {
      id: node.dataset.nodeId,
      kind: node.dataset.kind,
      faded: node.classList.contains("faded"),
      x: Math.round(box.left - base.left),
      y: Math.round(box.top - base.top),
      w: Math.round(box.width),
      h: Math.round(box.height),
      textW: textBox ? Math.round(textBox.width * ctm.a * 10) / 10 : null,
      textH: textBox ? Math.round(textBox.height * ctm.d * 10) / 10 : null,
    };
  });
  let overlaps = 0;
  const examples = [];
  const labelOverflows = [];
  for (let i = 0; i < nodes.length; i += 1) {
    const a = nodes[i];
    if (a.textW != null && a.textW > a.w + 0.6) labelOverflows.push([a.id, a.textW, a.w]);
    for (let j = i + 1; j < nodes.length; j += 1) {
      const b = nodes[j];
      if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) {
        overlaps += 1;
        if (examples.length < 8) examples.push([a.id, b.id]);
      }
    }
  }
  const state = window.__g2nGraph || {};
  return {
    nodeCount: nodes.length,
    kindCounts: nodes.reduce((acc, node) => { acc[node.kind] = (acc[node.kind] || 0) + 1; return acc; }, {}),
    edgeCount: canvas.querySelectorAll("line.graph-edge").length,
    overlaps,
    overlapExamples: examples,
    labelOverflows,
    minNodeWidth: Math.min(...nodes.map((node) => node.w)),
    canvas: { width: Math.round(base.width), height: Math.round(base.height) },
    screenCTM: { a: Math.round(ctm.a * 10000) / 10000, d: Math.round(ctm.d * 10000) / 10000 },
    zoomLabel: document.getElementById("graph-zoom-value") ? document.getElementById("graph-zoom-value").textContent : "n/a",
    viewBox: canvas.getAttribute("viewBox"),
    layout: state.layout || null,
    fadedNodes: nodes.filter((node) => node.faded).length,
    fadedEdges: canvas.querySelectorAll("line.graph-edge.faded").length,
    status: document.getElementById("graph-status") ? document.getElementById("graph-status").textContent : "",
    sourceActive: [...document.querySelectorAll("#graph-source-chips button")].map((b) => [b.dataset.source, b.classList.contains("active")]),
    version: state.version || 0,
  };
})()`;

async function settle(cdp, expression, expectedVersion = null) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const value = await cdp.evaluate(expression);
    if (value != null && (expectedVersion == null || value >= expectedVersion)) return value;
    await sleep(200);
  }
  return null;
}

const chrome = spawn(chromeBin, [
  "--remote-debugging-port=9333",
  "--user-data-dir=/tmp/u4-chrome-profile",
  "--remote-allow-origins=*",
  "--no-first-run",
  "--no-default-browser-check",
  "--window-size=1440,1000",
  `--app=${url}`,
], { stdio: ["ignore", "pipe", "pipe"] });
chrome.stderr.on("data", () => {});

const click = (selector) => `(() => {
  const node = document.querySelector(${JSON.stringify(selector)});
  if (!node) return "missing";
  node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  return "ok";
})()`;

async function main() {
  try {
      const target = await waitForTarget();
    const cdp = new CDP(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");

    const initialVersion = await settle(cdp, "window.__g2nGraph && window.__g2nGraph.version");
    const legacy = initialVersion == null;
    if (legacy) {
      // pre-U4 bundle (before-shot): the automation seam does not exist, wait for
      // the legacy single-pass render instead.
      const rendered = await settle(cdp,
        `document.querySelectorAll("g.graph-node").length || null`);
      if (rendered == null) throw new Error("graph view never rendered");
      await sleep(700);
    }

    const metrics = { url, viewport: { width: 1440, height: 1000 }, initialVersion, legacy };
    metrics.initial = await cdp.evaluate(measureExpression);

    if (legacy) {
      // the pre-U4 view has no toolbar / filters / clusters: record its baseline
      // and stop after the screenshot.
      const legacyShot = await cdp.send("Page.captureScreenshot", { format: "png" });
      fs.writeFileSync(outJson, JSON.stringify(metrics, null, 2));
      fs.writeFileSync(outPng, Buffer.from(legacyShot.data, "base64"));
      cdp.close();
      console.log(JSON.stringify({ ok: true, legacy: true, png: outPng, json: outJson }, null, 2));
      return;
    }

    // ---- zoom range (0.25x-4x) + wheel zoom ------------------------------
    metrics.zoom = await cdp.evaluate(`(() => {
      const canvas = document.getElementById("graph-canvas");
      const label = () => document.getElementById("graph-zoom-value").textContent;
      const counts = () => canvas.querySelectorAll("g.graph-node").length;
      const record = { steps: [] };
      for (let i = 0; i < 20; i += 1) {
        document.getElementById("graph-zoom-in").dispatchEvent(new MouseEvent("click", { bubbles: true }));
        if (i % 6 === 0) record.steps.push(["in", label(), counts()]);
      }
      record.max = { label: label(), nodes: counts(), viewBox: canvas.getAttribute("viewBox") };
      for (let i = 0; i < 60; i += 1) {
        document.getElementById("graph-zoom-out").dispatchEvent(new MouseEvent("click", { bubbles: true }));
        if (i % 8 === 0) record.steps.push(["out", label(), counts()]);
      }
      record.min = { label: label(), nodes: counts(), viewBox: canvas.getAttribute("viewBox") };
      document.getElementById("graph-fit").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      record.fit = { label: label(), nodes: counts(), viewBox: canvas.getAttribute("viewBox") };
      // wheel zoom about the cursor
      const rect = canvas.getBoundingClientRect();
      canvas.dispatchEvent(new WheelEvent("wheel", {
        bubbles: true, cancelable: true, deltaY: -120,
        clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2,
      }));
      record.afterWheelIn = { label: label(), viewBox: canvas.getAttribute("viewBox") };
      canvas.dispatchEvent(new WheelEvent("wheel", {
        bubbles: true, cancelable: true, deltaY: 240,
        clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2,
      }));
      record.afterWheelOut = { label: label(), viewBox: canvas.getAttribute("viewBox") };
      // drag pan
      const before = canvas.getAttribute("viewBox");
      canvas.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerId: 1, clientX: rect.left + 40, clientY: rect.top + 40 }));
      canvas.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 1, clientX: rect.left + 120, clientY: rect.top + 90 }));
      canvas.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, pointerId: 1, clientX: rect.left + 120, clientY: rect.top + 90 }));
      record.panBefore = before;
      record.panAfter = canvas.getAttribute("viewBox");
      document.getElementById("graph-fit").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      return record;
    })()`);
    metrics.zoom.min.labelShouldBe = "25%";

    // ---- focus neighbourhood (click document, then empty space) -----------
    await cdp.evaluate(`location.hash = "#graph?clusters=expand"; null`);
    await settle(cdp, "window.__g2nGraph.version");
    await sleep(800);
    await cdp.evaluate(`(() => {
      const doc = [...document.querySelectorAll("g.graph-node[data-kind=document]")].find((n) => !n.classList.contains("faded"));
      if (doc) window.__u4FocusNode = doc.dataset.nodeId;
    })()`);
    const beforeFocusVersion = await cdp.evaluate("window.__g2nGraph.version");
    metrics.focus = await cdp.evaluate(`(() => {
      const doc = [...document.querySelectorAll("g.graph-node[data-kind=document]")].find((n) => !n.classList.contains("faded"));
      if (!doc) return { error: "no document node" };
      const id = doc.dataset.nodeId;
      doc.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      return { focusId: id, hashBefore: location.hash };
    })()`);
    await settle(cdp, "window.__g2nGraph.version", beforeFocusVersion + 1);
    const focusState = await cdp.evaluate(measureExpression);
    metrics.focus.after = {
      faded: focusState.fadedNodes,
      fadedEdges: focusState.fadedEdges,
      status: focusState.status,
      focusId: await cdp.evaluate("window.__g2nGraph.focusId"),
      hash: await cdp.evaluate("location.hash"),
    };
    const clearVersion = await cdp.evaluate("window.__g2nGraph.version");
    await cdp.evaluate(`document.getElementById("graph-canvas").dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))`);
    await settle(cdp, "window.__g2nGraph.version", clearVersion + 1);
    metrics.focus.cleared = {
      faded: (await cdp.evaluate(measureExpression)).fadedNodes,
      focusId: await cdp.evaluate("window.__g2nGraph.focusId"),
    };

    metrics.focus.documentView = await cdp.evaluate(measureExpression);

    // ---- navigation (document double-click / topic+tag single click) ------
    metrics.navigation = { document: await cdp.evaluate(`(() => {
      const doc = [...document.querySelectorAll("g.graph-node[data-kind=document]")][0];
      doc.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, cancelable: true }));
      return { node: doc.dataset.nodeId, route: doc.dataset.route, hash: location.hash };
    })()`) };
    await sleep(900);
    metrics.navigation.document.hashAfterWait = await cdp.evaluate("location.hash");
    metrics.navigation.document.editorVisible = await cdp.evaluate(
      `!document.getElementById("work-zone").classList.contains("hidden")`,
    );

    await cdp.evaluate(`location.hash = "#graph?clusters=expand"; null`);
    await settle(cdp, "window.__g2nGraph.version");
    await sleep(700);
    metrics.navigation.topic = await cdp.evaluate(`(() => {
      const node = document.querySelector('g.graph-node[data-kind=topic]');
      return { route: node.dataset.route, id: node.dataset.nodeId };
    })()`);
    await cdp.evaluate(click("g.graph-node[data-kind=topic]"));
    await sleep(500);
    await cdp.evaluate(click("g.graph-node[data-kind=topic]"));
    await sleep(900);
    metrics.navigation.topic.hashAfterWait = await cdp.evaluate("location.hash");
    metrics.navigation.topic.libraryVisible = await cdp.evaluate(
      `!document.getElementById("library-zone").classList.contains("hidden")`,
    );

    await cdp.evaluate(`location.hash = "#graph?clusters=expand"; null`);
    await settle(cdp, "window.__g2nGraph.version");
    await sleep(700);
    metrics.navigation.tag = await cdp.evaluate(`(() => {
      const node = document.querySelector('g.graph-node[data-kind=tag]');
      return { route: node.dataset.route, id: node.dataset.nodeId };
    })()`);
    await cdp.evaluate(click("g.graph-node[data-kind=tag]"));
    await sleep(500);
    await cdp.evaluate(click("g.graph-node[data-kind=tag]"));
    await sleep(900);
    metrics.navigation.tag.hashAfterWait = await cdp.evaluate("location.hash");
    metrics.navigation.tag.libraryVisible = await cdp.evaluate(
      `!document.getElementById("library-zone").classList.contains("hidden")`,
    );

    // ---- source filter (disable manual) ----------------------------------
    await cdp.evaluate(`location.hash = "#graph?clusters=expand"; null`);
    await settle(cdp, "window.__g2nGraph.version");
    await sleep(800);
    const beforeFilterVersion = await cdp.evaluate("window.__g2nGraph.version");
    await cdp.evaluate(click('#graph-source-chips button[data-source="manual"]'));
    await settle(cdp, "window.__g2nGraph.version", beforeFilterVersion + 1);
    await sleep(600);
    metrics.filterManual = await cdp.evaluate(measureExpression);
    metrics.filterManual.sources = await cdp.evaluate("window.__g2nGraph.sources");
    metrics.filterManual.hash = await cdp.evaluate("location.hash");

    // ---- tag filter (single tag) -----------------------------------------
    await cdp.evaluate(`location.hash = "#graph?clusters=expand"; null`);
    await settle(cdp, "window.__g2nGraph.version");
    await sleep(800);
    const beforeTagVersion = await cdp.evaluate("window.__g2nGraph.version");
    await cdp.evaluate(click("#graph-tag-chips button.graph-chip"));
    await settle(cdp, "window.__g2nGraph.version", beforeTagVersion + 1);
    await sleep(600);
    metrics.filterTag = await cdp.evaluate(measureExpression);
    metrics.filterTag.tags = await cdp.evaluate("window.__g2nGraph.tags");
    metrics.filterTag.hash = await cdp.evaluate("location.hash");

    // ---- clear filters ----------------------------------------------------
    const beforeClearVersion = await cdp.evaluate("window.__g2nGraph.version");
    await cdp.evaluate(click("#graph-clear-filters"));
    await settle(cdp, "window.__g2nGraph.version", beforeClearVersion + 1);
    await sleep(600);
    metrics.cleared = await cdp.evaluate(measureExpression);

    // ---- cluster convergence toggle --------------------------------------
    await cdp.evaluate(`location.hash = "#graph"; null`);
    await settle(cdp, "window.__g2nGraph.version");
    await sleep(900);
    metrics.cluster = { collapsed: await cdp.evaluate(measureExpression) };
    // click one aggregate node -> that cluster expands inline
    const firstCluster = await cdp.evaluate(
      `(document.querySelector("g.graph-node[data-cluster]") || {}).dataset?.cluster || null`,
    );
    const beforeClusterClick = await cdp.evaluate("window.__g2nGraph.version");
    await cdp.evaluate(`(() => {
      const node = document.querySelector("g.graph-node[data-cluster]");
      if (node) node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    })()`);
    await settle(cdp, "window.__g2nGraph.version", beforeClusterClick + 1);
    await sleep(700);
    metrics.cluster.expanded = await cdp.evaluate(measureExpression);
    metrics.cluster.inline = {
      clicked: firstCluster,
      documentsAfter: metrics.cluster.expanded.kindCounts.document || 0,
      clustersAfter: metrics.cluster.expanded.kindCounts.cluster || 0,
    };
    const beforeToggleVersion = await cdp.evaluate("window.__g2nGraph.version");
    await cdp.evaluate(click("#graph-clusters-toggle"));
    await settle(cdp, "window.__g2nGraph.version", beforeToggleVersion + 1);
    await sleep(900);
    metrics.cluster.toggled = await cdp.evaluate(measureExpression);
    metrics.cluster.toggleClicks = 2;

    // screenshot of the default (converged) view
    await cdp.evaluate(`location.hash = "#graph"; null`);
    await settle(cdp, "window.__g2nGraph.version");
    await sleep(900);
    const shot = await cdp.send("Page.captureScreenshot", { format: "png" });

    fs.writeFileSync(outJson, JSON.stringify(metrics, null, 2));
    fs.writeFileSync(outPng, Buffer.from(shot.data, "base64"));
    cdp.close();
    console.log(JSON.stringify({ ok: true, png: outPng, json: outJson }, null, 2));
  } finally {
    chrome.kill("SIGTERM");
    await sleep(400);
    try { chrome.kill("SIGKILL"); } catch (_) { /* already gone */ }
  }

}

main().catch((error) => { console.error(error); process.exit(1); });
