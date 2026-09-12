// Node unit test for the P3 unified search panel pure helpers (no browser).
// Run: node tests/search_panel.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const modulePath = path.join(here, "..", "graph2note", "webstatic", "search-panel.js");
const panel = await import(pathToFileURL(modulePath).href);

// ---- 1) results are grouped into documents / PDF pages --------------------
const payload = {
  query: "状态空间",
  tokens: ["状态空间"],
  documents: [{ kind: "document", document_id: "d1", title: "手稿A" }],
  pdf_pages: [{ kind: "pdf_page", document_id: "p1", pdf_id: "pdf-1", page_index: 1 }],
};
const grouped = panel.groupSearchResults(payload);
assert.strictEqual(grouped.documents.length, 1);
assert.strictEqual(grouped.pdfPages.length, 1);
assert.strictEqual(grouped.documents[0].document_id, "d1");
// tolerates a payload without the `groups` key and never aliases the input
assert.deepStrictEqual(panel.groupSearchResults({}).documents, []);
assert.deepStrictEqual(panel.groupSearchResults({ pdf_pages: [{ page_index: 0 }] }).pdfPages.length, 1);

// ---- 2) page display falls back to the 1-based original order -------------
assert.strictEqual(panel.displayPage({ page_number: 7, page_index: 3 }), 7);
assert.strictEqual(panel.displayPage({ page_number: null, page_index: 3 }), 4);
assert.strictEqual(panel.displayPage({}), 1);

// ---- 3) cross-view "ask about these results" state transfer ---------------
function fakeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    _map: map,
  };
}
const storage = fakeStorage();
assert.strictEqual(panel.readPendingAsk(storage), "");
assert.strictEqual(panel.writePendingAsk(storage, "  卡尔曼滤波  "), "卡尔曼滤波");
assert.strictEqual(storage.getItem(panel.PENDING_ASK_KEY), "卡尔曼滤波");
assert.strictEqual(panel.readPendingAsk(storage), "卡尔曼滤波");
panel.clearPendingAsk(storage);
assert.strictEqual(panel.readPendingAsk(storage), "");
// an empty query never writes a pending ask
assert.strictEqual(panel.writePendingAsk(storage, "   "), "");
assert.strictEqual(panel.readPendingAsk(storage), "");

// ---- 4) the QA destination route is detected from the shell ---------------
const legacyDoc = { getElementById: () => null };
const u1Doc = { getElementById: (id) => (id === "pdf-search-zone" ? {} : null) };
assert.strictEqual(panel.qaRoute(legacyDoc), "#library");
assert.strictEqual(panel.qaRoute(u1Doc), "#pdf-search");

// ---- 5) init is a no-op without the panel markup --------------------------
assert.strictEqual(panel.initSearchPanel({ document: legacyDoc, window: {} }), null);

// ---- 6) live behaviour with a tiny DOM stub: ⌘K / Esc / ask hand-off ------
const PANEL_IDS = [
  "global-search-panel", "global-search-input", "global-search-panel-input",
  "global-search-status", "global-search-results", "global-search-documents",
  "global-search-pdf-pages", "global-search-documents-count",
  "global-search-pdf-count", "global-search-close", "global-search-ask",
  "global-search-form", "pdf-qa-input",
];

function fakeElement(tag = "div", id = "") {
  const listeners = new Map();
  const classes = new Set(id === "global-search-panel" ? ["hidden"] : []);
  return {
    tagName: tag.toUpperCase(), id, className: "", dataset: {}, children: [],
    textContent: "", innerHTML: "", value: "", href: "", target: "", rel: "",
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
    },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    dispatch(type, event) { for (const fn of listeners.get(type) || []) fn(event); },
    appendChild(child) { this.children.push(child); return child; },
    focus() { doc.activeElement = this; },
    blur() { if (doc.activeElement === this) doc.activeElement = null; },
    scrollIntoView() {},
  };
}

const nodes = new Map();
for (const id of PANEL_IDS) {
  const tag = id.includes("input") ? "input" : (id === "global-search-form" ? "form" : "div");
  nodes.set(id, fakeElement(tag, id));
}
const doc = {
  activeElement: null,
  body: fakeElement("body", "body"),
  getElementById: (id) => nodes.get(id) || null,
  createElement: (tag) => fakeElement(tag),
  createTextNode: (text) => { const node = fakeElement("text"); node.textContent = text; return node; },
  addEventListener(type, fn) { if (!this._l) this._l = new Map(); if (!this._l.has(type)) this._l.set(type, []); this._l.get(type).push(fn); },
  dispatch(type, event) { for (const fn of (this._l && this._l.get(type)) || []) fn(event); },
};
const sessionStore = fakeStorage();
const fetchCalls = [];
const fakePayload = { query: "状态空间", tokens: ["状态空间"], total: 2,
  documents: [{ kind: "document", document_id: "d1", title: "手稿A", score: 3 }],
  pdf_pages: [{ kind: "pdf_page", document_id: "p1", pdf_id: "pdf-1",
                page_index: 1, page_number: 2, score: 2 }] };
const fakeWin = {
  location: { hash: "#library" },
  sessionStorage: sessionStore,
  fetch: (url) => { fetchCalls.push(url); return Promise.resolve({ json: async () => fakePayload }); },
  addEventListener(type, fn) { if (!this._l) this._l = new Map(); if (!this._l.has(type)) this._l.set(type, []); this._l.get(type).push(fn); },
  dispatch(type, event) { for (const fn of (this._l && this._l.get(type)) || []) fn(event); },
  open() { fakeWin.opened = true; },
};

const api = panel.initSearchPanel({ document: doc, window: fakeWin });
assert.ok(api, "panel should initialise with the markup present");
const panelNode = nodes.get("global-search-panel");
const keyEvent = (key, extra = {}) => ({ key, metaKey: false, ctrlKey: false, target: doc.body, preventDefault() {}, ...extra });

// ⌘K opens from a non-input focus target
assert.ok(panelNode.classList.contains("hidden"));
doc.dispatch("keydown", keyEvent("k", { metaKey: true }));
assert.ok(!panelNode.classList.contains("hidden"), "⌘K opens the panel");
// Esc closes it again
doc.dispatch("keydown", keyEvent("Escape"));
assert.ok(panelNode.classList.contains("hidden"), "Esc closes the panel");
// ⌘K inside a text field is ignored (never steals the shortcut)
doc.activeElement = null;
doc.dispatch("keydown", keyEvent("k", { metaKey: true, target: { tagName: "INPUT" } }));
assert.ok(panelNode.classList.contains("hidden"), "⌘K inside an input is ignored");

// grouped results render through /api/search (documents / PDF pages)
api.open("状态空间");
await new Promise((resolve) => setTimeout(resolve, 20));
assert.strictEqual(fetchCalls.length, 1);
assert.ok(fetchCalls[0].startsWith("/api/search?q="));
assert.strictEqual(nodes.get("global-search-documents").children.length, 1);
assert.strictEqual(nodes.get("global-search-pdf-pages").children.length, 1);
assert.strictEqual(nodes.get("global-search-documents").children[0].dataset.kind, "document");
assert.strictEqual(nodes.get("global-search-pdf-pages").children[0].dataset.kind, "pdf_page");

// "就这些结果提问" carries the query across views and prefills the Q&A input
// (a) different view: pending ask is stored, then consumed on arrival
fakeWin.location.hash = "#timeline";
api.open("状态空间");
api.askAboutResults();
assert.strictEqual(panel.readPendingAsk(sessionStore), "状态空间");
assert.strictEqual(fakeWin.location.hash, "#library");
assert.ok(panelNode.classList.contains("hidden"));
api.applyPendingAsk();
assert.strictEqual(nodes.get("pdf-qa-input").value, "状态空间");
assert.strictEqual(panel.readPendingAsk(sessionStore), "");
// (b) already on the Q&A view: prefill happens in place
fakeWin.location.hash = "#library";
api.open("注意力机制");
api.askAboutResults();
assert.strictEqual(nodes.get("pdf-qa-input").value, "注意力机制");
assert.strictEqual(panel.readPendingAsk(sessionStore), "");

console.log("search_panel: all assertions passed ✓");
