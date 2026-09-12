// Offline DOM behaviour test for the U3 editor workspace (side-panel forms,
// viewer, shortcuts).  No browser, no network, no npm: a tiny DOM shim plus a
// scripted `fetch` replay exercises the real `/static/js/views/document.js`
// module.  Run: node tests/editor_workspace_dom.mjs
//
// Contract asserted: every side-panel form drives the same API and refreshes
// the same shared state as before the layout migration (tags incl. A1
// auto/manual provenance, collections, time metadata + needs-organization),
// and the U3 additions (side-panel toggle, big-image viewer, ⌘S/⌘//Esc) work
// from the DOM.
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(here, "..", "graph2note", "webstatic", "js");

const delay = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));
const escapeHtml = (value) => String(value == null ? "" : value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

/* ------------------------------------------------------------------ DOM shim */

// Buttons are rendered through innerHTML with data-* attributes and then
// selected by attribute (`querySelectorAll("button[data-remove-tag]")`).  The
// shim mirrors exactly that contract.
function parseButtons(host, selector) {
  const match = /^button\[data-([a-z-]+)\]$/.exec(selector);
  if (!match) return [];
  const attr = match[1];
  const datasetKey = attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  const re = new RegExp(`data-${attr}="([^"]*)"`, "g");
  const out = [];
  let found;
  while ((found = re.exec(host.innerHTML)) !== null) {
    const button = makeEl("button");
    button.dataset[datasetKey] = found[1];
    out.push(button);
  }
  return out;
}

function makeEl(tag = "div", id = null) {
  const listeners = new Map();
  const classes = new Set();
  const attrs = new Map();
  const el = {
    tagName: String(tag).toUpperCase(),
    id,
    value: "",
    checked: false,
    textContent: "",
    src: "",
    disabled: false,
    isContentEditable: false,
    style: {},
    dataset: {},
    children: [],
    _html: "",
    classList: {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c),
      toggle: (c, force) => {
        const on = force === undefined ? !classes.has(c) : Boolean(force);
        if (on) classes.add(c); else classes.delete(c);
        return on;
      },
    },
    setAttribute(k, v) { attrs.set(k, String(v)); },
    getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
    removeAttribute(k) { attrs.delete(k); },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    removeEventListener(type, fn) {
      const list = listeners.get(type) || [];
      const i = list.indexOf(fn);
      if (i >= 0) list.splice(i, 1);
    },
    dispatch(type, event = {}) {
      const base = { type, preventDefault() {}, stopPropagation() {} };
      for (const fn of [...(listeners.get(type) || [])]) fn({ ...base, ...event });
    },
    appendChild(child) { el.children.push(child); return child; },
    focus() { globalThis.document.activeElement = el; },
    blur() { if (globalThis.document.activeElement === el) globalThis.document.activeElement = null; },
    click() { el.dispatch("click"); },
    select() {},
    querySelector(selector) { return el.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      // Cache per (selector, innerHTML) so the buttons handed to the module for
      // listener wiring are the same objects the test later dispatches on.
      const key = `${selector}|${el.innerHTML}`;
      el._cache = el._cache || new Map();
      if (!el._cache.has(key)) el._cache.set(key, parseButtons(el, selector));
      return el._cache.get(key);
    },
    getBoundingClientRect() { return { left: 0, top: 0, width: 900, height: 700, right: 900, bottom: 700 }; },
    clientWidth: 900,
    clientHeight: 700,
    naturalWidth: 0,
    naturalHeight: 0,
    complete: false,
    setPointerCapture() {},
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html || escapeHtml(el.textContent); },
    set(v) { el._html = String(v); },
  });
  return el;
}

const elementCache = new Map();
const documentShim = {
  activeElement: null,
  createElement: (tag) => makeEl(tag),
  querySelector(selector) {
    if (!elementCache.has(selector)) {
      const id = selector.startsWith("#") ? selector.slice(1) : null;
      const tag = id === "md-editor" ? "textarea"
        : id === "document-tag-input" ? "input"
          : id === "metadata-document-time" ? "input"
            : id === "metadata-needs-organization" ? "input"
              : id === "document-collection-select" ? "select" : "div";
      elementCache.set(selector, makeEl(tag, id));
    }
    return elementCache.get(selector);
  },
  querySelectorAll: () => [],
  addEventListener(type, fn) { documentShim._listeners.push({ type, fn }); },
  dispatch(type, event = {}) {
    const base = { type, preventDefault() {}, stopPropagation() {} };
    for (const { type: t, fn } of [...documentShim._listeners]) if (t === type) fn({ ...base, ...event });
  },
  execCommand() {},
  _listeners: [],
};

globalThis.document = documentShim;
globalThis.window = { addEventListener() {}, confirm: () => true, prompt: () => null, marked: undefined };
globalThis.location = { hash: "#doc/d1" };

const el = (selector) => documentShim.querySelector(selector);

/* ------------------------------------------------------------- fetch replay */

const calls = [];
let docRecord;

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: { get: () => "application/json" },
    json: async () => JSON.parse(JSON.stringify(body)),
    blob: async () => body,
  };
}

function tagResult(tags, provenance) {
  return { tags, tag_provenance: provenance, tags_detail: [] };
}

globalThis.fetch = async (url, opts = {}) => {
  const route = String(url);
  const method = (opts.method || "GET").toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : null;
  calls.push({ route, method, body });
  if (route === "/api/documents/d1" && method === "GET") return jsonResponse(docRecord);
  if (route === "/api/collections" && method === "GET") {
    return jsonResponse([
      { collection_id: "c1", name: "数学笔记", document_count: 1 },
      { collection_id: "c2", name: "阅读", document_count: 0 },
    ]);
  }
  if (/\/api\/documents\/d1\/tags\/manual$/.test(route) && method === "POST") {
    const tags = [...docRecord.tags, body.tag];
    docRecord.tag_provenance = { ...docRecord.tag_provenance, [body.tag]: "manual" };
    return jsonResponse(tagResult(tags, docRecord.tag_provenance));
  }
  if (/\/api\/documents\/d1\/tags\/[^/]+$/.test(route) && method === "DELETE") {
    const tag = decodeURIComponent(route.split("/tags/")[1]);
    const tags = docRecord.tags.filter((t) => t !== tag);
    delete docRecord.tag_provenance[tag];
    return jsonResponse(tagResult(tags, docRecord.tag_provenance));
  }
  if (/\/api\/documents\/d1\/tags\/[^/]+$/.test(route) && method === "PATCH") {
    const tag = decodeURIComponent(route.split("/tags/")[1]);
    docRecord.tag_provenance = { ...docRecord.tag_provenance, [tag]: body.provenance };
    return jsonResponse(tagResult(docRecord.tags, docRecord.tag_provenance));
  }
  if (/\/api\/documents\/d1\/collections$/.test(route) && method === "PUT") {
    docRecord.collections = [...body.collection_ids];
    return jsonResponse({ document_id: "d1", collections: docRecord.collections });
  }
  if (/\/api\/documents\/d1\/metadata$/.test(route) && method === "PUT") {
    docRecord.metadata = {
      ...docRecord.metadata,
      document_time: { value: body.document_time, source: body.document_time ? "manual" : "none" },
      needs_organization: body.needs_organization,
    };
    return jsonResponse({ metadata: docRecord.metadata });
  }
  if (/\/api\/documents\/d1\/markdown$/.test(route) && method === "POST") {
    docRecord.current_markdown = body.markdown;
    return jsonResponse({ ok: true, updated_at: "2026-03-16T12:00:00" });
  }
  throw new Error(`unexpected fetch ${method} ${route}`);
};

/* ------------------------------------------------------------------- module */

const documentModule = await import(pathToFileURL(path.join(JS, "views", "document.js")).href);
const { state } = await import(pathToFileURL(path.join(JS, "state.js")).href);

function freshDoc() {
  return {
    document_id: "d1",
    title: "线性代数手稿 p3",
    current_markdown: "# 原文\n\n核与像。\n",
    latest: { model: "glm-5.3-flash" },
    latest_version: "v2",
    versions: [
      { version_id: "v1", created_at: "2026-03-14T09:00:00", model: "glm-5.3-flash" },
      { version_id: "v2", created_at: "2026-03-15T09:00:00", model: "glm-5.3-flash" },
    ],
    tags: ["已确认", "待复习"],
    tag_provenance: { "已确认": "manual", "待复习": "auto" },
    tags_detail: [],
    collections: ["c1"],
    metadata: {
      document_time: { value: "2026-03-14", source: "manual" },
      capture_time: { value: null },
      import_time: { value: "2026-03-15T10:00:00" },
      modified_time: { value: "2026-03-16T11:00:00" },
      effective_time: { value: "2026-03-14", source: "manual" },
      needs_organization: true,
      evidence: "手写日期 2026-03-14",
      confidence: "high",
    },
  };
}

/* ---------------------------------------------------------------- 1) load */

docRecord = freshDoc();
documentModule.renderDocumentRoute({ name: "doc", id: "d1" });
await delay(30);

assert(state.docId === "d1");
assert(el("#md-editor").value === "# 原文\n\n核与像。\n", "markdown loaded into editor");
assert(calls.some((c) => c.method === "GET" && c.route === "/api/documents/d1"));

// A1 provenance preserved inside the side panel
assert(el("#document-tag-list").innerHTML.includes("data-tag=\"已确认\""), "manual tag rendered");
assert(el("#document-tag-list").innerHTML.includes("data-promote-tag=\"待复习\""), "auto tag keeps promote button");
assert(el("#document-tag-list").innerHTML.includes("tag-auto-badge"), "auto badge present");
assert(el("#document-tag-list").querySelectorAll("button[data-remove-tag]").length === 2,
  "remove buttons wired for both tags");

// metadata + needs-organization
assert(el("#metadata-document-time").value === "2026-03-14");
assert(el("#metadata-needs-organization").checked === true);

// collections
assert(el("#document-collection-list").innerHTML.includes("数学笔记"));

// version info lives in the side panel and lists newest first
const versionHtml = el("#version-list").innerHTML;
assert(versionHtml.indexOf("v2") < versionHtml.indexOf("v1"), "versions newest-first");
assert(versionHtml.includes("current"), "current version flagged");
assert(el("#version-info").textContent.includes("第 2 版"));

// default-collapsed side panel
assert(el("#doc-side-panel").classList.contains("hidden"), "side panel collapsed after load");
assert(el("#doc-panel-toggle").getAttribute("aria-expanded") === "false");

/* ------------------------------------------------ 2) tags: form -> API -> DOM */

el("#document-tag-input").value = "  新标签  ";
el("#document-tag-form").dispatch("submit");
await delay(20);
const addCall = calls.find((c) => c.method === "POST" && c.route.endsWith("/tags/manual"));
assert(addCall && addCall.body.tag === "新标签", "tag form POSTs trimmed tag");
assert(state.doc.tags.includes("新标签"), "state.doc.tags updated");
assert(el("#document-tag-list").innerHTML.includes("新标签"), "tag list re-rendered");
assert(el("#document-tag-input").value === "", "input cleared after submit");

/* 2b) remove tag */
let removeButton = el("#document-tag-list").querySelectorAll("button[data-remove-tag]")
  .find((b) => b.dataset.removeTag === "已确认");
assert(removeButton, "remove button for 已确认 present");
removeButton.dispatch("click");
await delay(20);
assert(calls.some((c) => c.method === "DELETE" && c.route === "/api/documents/d1/tags/%E5%B7%B2%E7%A1%AE%E8%AE%A4"
  || c.method === "DELETE" && decodeURIComponent(c.route.split("/tags/")[1]) === "已确认"), "DELETE tag called");
assert(!state.doc.tags.includes("已确认"), "state.doc.tags no longer has removed tag");
assert(!el("#document-tag-list").innerHTML.includes("data-tag=\"已确认\""), "removed tag gone from DOM");

/* 2c) promote auto -> manual (A1 red line) */
const promoteButton = el("#document-tag-list").querySelectorAll("button[data-promote-tag]")
  .find((b) => b.dataset.promoteTag === "待复习");
assert(promoteButton, "promote button for auto tag present");
promoteButton.dispatch("click");
await delay(20);
const patchCall = calls.find((c) => c.method === "PATCH");
assert(patchCall && patchCall.body.provenance === "manual", "PATCH provenance=manual");
assert(state.doc.tag_provenance["待复习"] === "manual", "provenance state updated");
assert(!el("#document-tag-list").innerHTML.includes("data-promote-tag=\"待复习\""), "promote button gone after manual");

/* --------------------------------------- 3) collections: form -> API -> DOM */

el("#document-collection-select").innerHTML = "<option value=\"c2\">阅读</option>";
el("#document-collection-select").value = "c2";
el("#document-collection-form").dispatch("submit");
await delay(20);
const collPut = calls.filter((c) => c.method === "PUT" && c.route.endsWith("/collections")).at(-1);
assert(collPut && collPut.body.collection_ids.includes("c1") && collPut.body.collection_ids.includes("c2"),
  "collection add PUTs full id list");
assert(state.doc.collections.includes("c2"), "state.doc.collections updated");
assert(el("#document-collection-list").innerHTML.includes("阅读"), "collection list re-rendered");

const removeCollection = el("#document-collection-list").querySelectorAll("button[data-remove-collection]")
  .find((b) => b.dataset.removeCollection === "c1");
assert(removeCollection, "remove-collection button present");
removeCollection.dispatch("click");
await delay(20);
const collPut2 = calls.filter((c) => c.method === "PUT" && c.route.endsWith("/collections")).at(-1);
assert(!collPut2.body.collection_ids.includes("c1"), "collection remove PUTs remaining ids");
assert(!state.doc.collections.includes("c1"));

/* ------------------------------------------ 4) metadata: change -> API -> DOM */

el("#metadata-document-time").value = "2024-01-02";
el("#metadata-needs-organization").checked = false;
el("#metadata-document-time").dispatch("change");
await delay(20);
const metaPut = calls.filter((c) => c.method === "PUT" && c.route.endsWith("/metadata")).at(-1);
assert(metaPut.body.document_time === "2024-01-02", "metadata PUT sends date");
assert(metaPut.body.needs_organization === false, "metadata PUT sends needs_organization");
assert(state.doc.metadata.document_time.value === "2024-01-02", "metadata state updated");
assert(el("#metadata-save").textContent === "已保存", "metadata save feedback");

/* ------------------------------------------------- 5) side panel + shortcuts */

documentModule.toggleSidePanel(false);
documentShim.dispatch("keydown", { key: "/", metaKey: true });
assert(!el("#doc-side-panel").classList.contains("hidden"), "⌘/ opens side panel");
assert(globalThis.document.activeElement === null, "no accidental focus change");

el("#document-tag-input").focus();
documentShim.dispatch("keydown", { key: "/", metaKey: true });
assert(!el("#doc-side-panel").classList.contains("hidden"), "⌘/ does not hijack while typing");
el("#document-tag-input").blur();
documentShim.dispatch("keydown", { key: "/", metaKey: true });
assert(el("#doc-side-panel").classList.contains("hidden"), "⌘/ toggles panel closed");

/* ------------------------------------------------------------ 6) image viewer */

assert(documentModule.viewerSource() === "/api/documents/d1/preprocessed", "image upload source");
documentModule.openImageViewer();
assert(!el("#image-viewer").classList.contains("hidden"), "viewer opens");
assert(el("#image-viewer-img").src === "/api/documents/d1/preprocessed");
for (let i = 0; i < 5; i += 1) documentModule.zoomImageViewer(1.25);
const zoomPct = Number(el("#viewer-zoom-label").textContent.replace("%", ""));
assert(zoomPct >= 200, `viewer zooms >=2x (got ${zoomPct}%)`);
assert(el("#image-viewer-img").style.transform.includes("scale("), "viewer transform applied");
documentModule.fitImageViewer();
assert(Boolean(el("#viewer-zoom-label").textContent), "fit updates zoom label");
documentModule.closeImageViewer();
assert(el("#image-viewer").classList.contains("hidden"), "viewer closes");

documentModule.openImageViewer();
documentShim.dispatch("keydown", { key: "Escape" });
assert(el("#image-viewer").classList.contains("hidden"), "Esc exits viewer");

/* PDF source page reuses /api/pdf page endpoint via the document endpoint */
state.doc = { ...state.doc, pdf_id: "pdf-1", page_index: 3 };
assert(documentModule.viewerSource() === "/api/documents/d1/source-page", "PDF source page source");
documentModule.openImageViewer();
assert(el("#image-viewer-img").src === "/api/documents/d1/source-page", "viewer renders PDF source page");
documentModule.closeImageViewer();
state.doc = { ...state.doc, pdf_id: null, page_index: null };

/* ------------------------------------------------------------- 7) ⌘S saves */

el("#md-editor").value = "# 编辑后的内容\n";
el("#md-editor").focus();                    // ⌘S must still work while typing
documentShim.dispatch("keydown", { key: "s", metaKey: true });
await delay(20);
const saveCall = calls.filter((c) => c.method === "POST" && c.route.endsWith("/markdown")).at(-1);
assert(saveCall && saveCall.body.markdown === "# 编辑后的内容\n", "⌘S posts editor markdown");
assert(el("#save-indicator").textContent.includes("（⌘S）"), "⌘S saved feedback");
assert(state.doc.current_markdown === "# 编辑后的内容\n", "saved markdown updates state");

console.log("editor_workspace_dom: all assertions passed ✓");
