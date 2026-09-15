// Offline DOM contract for the upload view's PDF interception (SPW Y3).
//
// The P1 source-string assertion (tests/test_papers_ingest_api.py) only proves
// the words are present: reversing the guard (`interceptPaperFile` returning
// early, an always-on zone, or images being swallowed too) stayed green.  This
// harness drives the *real* capture-phase handler under a tiny DOM shim and
// pins the behaviour matrix:
//
//   * a PDF `change` on the hidden file input, or a PDF `drop` on the upload
//     card (or one of its children) is intercepted: `preventDefault` +
//     `stopPropagation` run and the file enters `/api/papers/import`;
//   * JPG/PNG on the same zone is NOT intercepted: no `stopPropagation` and no
//     paper import, so the untouched image path still runs (`/api/parse`);
//   * events outside the zone are never intercepted.
//
// No browser, no network, no npm.  Run: node tests/upload_pdf_intercept.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(here, "..", "graph2note", "webstatic", "js");

/* ------------------------------------------------------------------ DOM shim */

function makeEl(tag = "div", id = null) {
  const listeners = new Map();
  const classes = new Set();
  const node = {
    tagName: String(tag).toUpperCase(),
    id,
    textContent: "",
    value: "",
    disabled: false,
    files: null,
    dataset: {},
    style: {},
    className: "",
    children: [],
    parentNode: null,
    onclick: null,
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
    setAttribute(k, v) { if (k === "id") node.id = String(v); },
    getAttribute() { return null; },
    removeAttribute() {},
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    removeEventListener(type, fn) {
      const list = listeners.get(type) || [];
      const i = list.indexOf(fn);
      if (i >= 0) list.splice(i, 1);
    },
    // Invoke this node's own listeners (used to prove the image path still runs).
    dispatch(type, event) {
      const ev = event || { type, preventDefault() {}, stopPropagation() {} };
      if (ev.type === undefined) ev.type = type;
      for (const fn of [...(listeners.get(type) || [])]) fn(ev);
    },
    appendChild(child) {
      child.parentNode = node;
      node.children.push(child);
      return child;
    },
    contains(other) {
      let cur = other;
      while (cur) { if (cur === node) return true; cur = cur.parentNode; }
      return false;
    },
    click() { node.dispatch("click"); if (typeof node.onclick === "function") node.onclick({}); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  return node;
}

const elementCache = new Map();
const documentShim = {
  activeElement: null,
  body: makeEl("body"),
  createElement: (tag) => makeEl(tag),
  querySelector(selector) {
    if (!elementCache.has(selector)) {
      const id = selector.startsWith("#") ? selector.slice(1) : null;
      const tag = id === "file-input" ? "input" : "div";
      elementCache.set(selector, makeEl(tag, id));
    }
    return elementCache.get(selector);
  },
  querySelectorAll: () => [],
  getElementById(id) { return documentShim.querySelector(`#${id}`); },
  addEventListener(type, fn, options) {
    const capture = options === true || Boolean(options && options.capture);
    documentShim._listeners.push({ type, fn, capture });
  },
  dispatch(type, event) {
    const ev = event || { type, preventDefault() {}, stopPropagation() {} };
    if (ev.type === undefined) ev.type = type;
    for (const rec of [...documentShim._listeners]) if (rec.type === type) rec.fn(ev);
  },
  _listeners: [],
};

globalThis.document = documentShim;
globalThis.window = { addEventListener() {} };
globalThis.location = { hash: "#upload" };
globalThis.FormData = class FormData {
  constructor() { this.entries = []; }
  append(name, value) { this.entries.push([name, value]); }
};

const fetchCalls = [];
const jsonResponse = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  statusText: "OK",
  headers: { get: () => "application/json" },
  json: async () => JSON.parse(JSON.stringify(body)),
});
globalThis.fetch = async (route, opts = {}) => {
  const url = String(route);
  fetchCalls.push({ route: url, method: (opts.method || "GET").toUpperCase(), body: opts.body });
  if (url === "/api/papers/import") return jsonResponse({ paper_id: "paper-1" });
  if (url === "/api/parse") return jsonResponse({ job_id: "job-1", document_id: "doc-1" });
  if (/^\/api\/papers\//.test(url)) {
    return jsonResponse({ status: "done", document_id: "doc-1", sections: 3, source: "text-layer" });
  }
  return jsonResponse({});
};

/* ------------------------------------------------------------- module import */

const upload = await import(pathToFileURL(path.join(JS, "views", "upload.js")).href);
const { el, state } = await import(pathToFileURL(path.join(JS, "state.js")).href);

/* ------------------------------------------------------------------ helpers */

const pdf = { name: "论文.pdf", size: 2048, type: "application/pdf" };
const jpg = { name: "photo.jpg", size: 2048, type: "image/jpeg" };
const png = { name: "scan.png", size: 2048, type: "image/png" };
const zone = { uploadCard: el.uploadCard, fileInput: el.fileInput };

const changeEvt = (target, file) => {
  target.files = file ? [file] : [];
  return {
    type: "change", target,
    preventDefault() { this.pd += 1; }, stopPropagation() { this.sp += 1; }, pd: 0, sp: 0,
  };
};
const dropEvt = (target, file) => ({
  type: "drop", target, dataTransfer: { files: file ? [file] : [] },
  preventDefault() { this.pd += 1; }, stopPropagation() { this.sp += 1; }, pd: 0, sp: 0,
});

const interceptsOnly = (evt) => evt.pd === 0 && evt.sp === 0;
const paperFetches = () => fetchCalls.filter((c) => c.route === "/api/papers/import").length;
const parseFetches = () => fetchCalls.filter((c) => c.route === "/api/parse").length;
const reset = () => { state.busy = false; clearInterval(state.pollTimer); state.pollTimer = null; };

/* ------------------------------------------------- 1) pure decision helpers */

assert.strictEqual(upload.isPdfFile(pdf), true, "*.pdf is a paper file");
assert.strictEqual(upload.isPdfFile({ name: "x.PDF" }), true, "extension match is case-insensitive");
assert.strictEqual(upload.isPdfFile(jpg), false, "jpg is not a paper file");
assert.strictEqual(upload.isPdfFile(png), false, "png is not a paper file");
assert.strictEqual(upload.isPdfFile(null), false, "no file is not a paper file");
assert.strictEqual(upload.isPdfFile({}), false, "nameless file is not a paper file");

assert.strictEqual(upload.paperFileFromEvent({ type: "drop", dataTransfer: { files: [pdf] } }), pdf);
assert.strictEqual(upload.paperFileFromEvent({ type: "change", target: { files: [jpg] } }), jpg);
assert.strictEqual(upload.paperFileFromEvent({ type: "drop" }), undefined, "drop without files is empty");

assert.strictEqual(upload.shouldInterceptPaperEvent(changeEvt(el.fileInput, pdf), zone), true);
assert.strictEqual(upload.shouldInterceptPaperEvent(dropEvt(el.uploadCard, pdf), zone), true);

const child = makeEl("span", "drop-child");
el.uploadCard.appendChild(child);
assert.strictEqual(upload.shouldInterceptPaperEvent(dropEvt(child, pdf), zone), true,
  "a drop on a card descendant stays on the zone");

const outside = makeEl("section", "library-zone");
assert.strictEqual(upload.shouldInterceptPaperEvent(changeEvt(outside, pdf), zone), false);
assert.strictEqual(upload.shouldInterceptPaperEvent(dropEvt(outside, pdf), zone), false);
assert.strictEqual(upload.shouldInterceptPaperEvent(changeEvt(el.fileInput, jpg), zone), false);
assert.strictEqual(upload.shouldInterceptPaperEvent(dropEvt(el.uploadCard, png), zone), false);
assert.strictEqual(upload.shouldInterceptPaperEvent(changeEvt(el.fileInput, null), zone), false);

/* -------------------------------------------- 2) wiring is capture-phase */

const capture = (type) => documentShim._listeners.filter((r) => r.type === type && r.capture).length;
assert.strictEqual(capture("change"), 1, "change is intercepted in the capture phase");
assert.strictEqual(capture("drop"), 1, "drop is intercepted in the capture phase");

/* ------------------------------- 3) real handler: PDF inside the zone wins */

reset();
let before = paperFetches();
let evt = changeEvt(el.fileInput, pdf);
documentShim.dispatch("change", evt);
await Promise.resolve();
assert.strictEqual(evt.pd, 1, "PDF change must preventDefault");
assert.strictEqual(evt.sp, 1, "PDF change must stopPropagation before image handlers");
assert.strictEqual(paperFetches(), before + 1, "PDF change enters the paper upload");

reset();
before = paperFetches();
evt = dropEvt(el.uploadCard, pdf);
documentShim.dispatch("drop", evt);
await Promise.resolve();
assert.strictEqual(evt.pd, 1, "PDF drop on the card must preventDefault");
assert.strictEqual(evt.sp, 1, "PDF drop on the card must stopPropagation");
assert.strictEqual(paperFetches(), before + 1, "PDF drop enters the paper upload");

reset();
before = paperFetches();
evt = dropEvt(child, pdf);
documentShim.dispatch("drop", evt);
await Promise.resolve();
assert.strictEqual(evt.pd, 1, "PDF drop on a card descendant must preventDefault");
assert.strictEqual(evt.sp, 1, "PDF drop on a card descendant must stopPropagation");
assert.strictEqual(paperFetches(), before + 1, "descendant drop enters the paper upload");

/* ----------------------------- 4) images keep the untouched image path */

reset();
before = paperFetches();
evt = changeEvt(el.fileInput, jpg);
documentShim.dispatch("change", evt);
assert.ok(interceptsOnly(evt), "JPG change must not be intercepted (no stopPropagation)");
assert.strictEqual(paperFetches(), before, "JPG change must not enter the paper upload");

reset();
evt = dropEvt(el.uploadCard, png);
documentShim.dispatch("drop", evt);
assert.ok(interceptsOnly(evt), "PNG drop must not be intercepted (no stopPropagation)");
assert.strictEqual(paperFetches(), before, "PNG drop must not enter the paper upload");

// The image handler upload.js registers on the file input still runs: a JPG
// picked there goes to the pre-existing /api/parse path.
reset();
before = parseFetches();
el.fileInput.dispatch("change", { target: { files: [jpg] } });
await Promise.resolve();
assert.strictEqual(parseFetches(), before + 1, "JPG picked on the input still uses the image path");

/* ---------------------------------------------- 5) outside the zone is inert */

reset();
before = paperFetches();
evt = changeEvt(outside, pdf);
documentShim.dispatch("change", evt);
assert.ok(interceptsOnly(evt), "PDF change off the zone must not be intercepted");

evt = dropEvt(outside, pdf);
documentShim.dispatch("drop", evt);
assert.ok(interceptsOnly(evt), "PDF drop off the zone must not be intercepted");
assert.strictEqual(paperFetches(), before, "off-zone PDFs never enter the paper upload");

clearInterval(state.pollTimer);
console.log("upload_pdf_intercept: all assertions passed ✓");
process.exit(0);
