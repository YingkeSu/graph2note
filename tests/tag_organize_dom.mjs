// Offline DOM contract test for the issue-01 tag governance review loop.
//
// Loads the real `/static/js/views/tags.js` module behind a tiny DOM shim and a
// scripted `fetch` replay, then drives the grouped render -> plan -> reject ->
// apply flow.  Run: node tests/tag_organize_dom.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(here, "..", "graph2note", "webstatic", "js");
const delay = (ms = 8) => new Promise((resolve) => setTimeout(resolve, ms));

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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
    disabled: false,
    textContent: "",
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
    dispatch(type, event = {}) {
      const base = { type, preventDefault() {}, stopPropagation() {} };
      for (const fn of [...(listeners.get(type) || [])]) fn({ ...base, ...event });
    },
    click() { el.dispatch("click"); },
    appendChild(child) { el.children.push(child); return child; },
    querySelector(selector) { return el.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      const key = `${selector}|${el.innerHTML}`;
      el._cache = el._cache || new Map();
      if (!el._cache.has(key)) el._cache.set(key, parseElements(el, selector));
      return el._cache.get(key);
    },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html || escapeHtml(el.textContent); },
    set(v) { el._html = String(v); },
  });
  return el;
}

// Parse `<tag ... data-attr="value" ...>` occurrences out of the current
// innerHTML; `checked` is reflected so checkbox state round-trips.
function parseElements(host, selector) {
  const match = /^([a-z]+)\[data-([a-z-]+)\]$/.exec(selector);
  if (!match) return [];
  const [, tag, attr] = match;
  const datasetKey = attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  const re = new RegExp(`<${tag}\\b[^>]*data-${attr}="([^"]*)"[^>]*>`, "g");
  const out = [];
  let found;
  while ((found = re.exec(host.innerHTML)) !== null) {
    const node = makeEl(tag);
    node.dataset[datasetKey] = found[1];
    node.checked = /\schecked(\s|>|\/)/.test(found[0]);
    out.push(node);
  }
  return out;
}

const elementCache = new Map();
const documentShim = {
  createElement: (tag) => makeEl(tag),
  querySelector(selector) {
    if (!elementCache.has(selector)) {
      const id = selector.startsWith("#") ? selector.slice(1) : null;
      elementCache.set(selector, makeEl(id === "tag-list" ? "div" : "div", id));
    }
    return elementCache.get(selector);
  },
  querySelectorAll: () => [],
  addEventListener() {},
};
globalThis.document = documentShim;
globalThis.window = { prompt: () => null, confirm: () => true, addEventListener() {} };
globalThis.location = { hash: "#tags" };

/* ------------------------------------------------------------- fetch replay */

const structureBefore = {
  groups: [{ name: "存储", size: 1, tags: [{ tag: "存储芯片", count: 1, aliases: [] }] }],
  ungrouped: [{ tag: "sram", count: 2, aliases: ["SRAM"] }],
};
const structureAfter = {
  groups: [{
    name: "存储", size: 2,
    tags: [
      { tag: "存储芯片", count: 2, aliases: ["sram", "SRAM"] },
      { tag: "dram", count: 1, aliases: [] },
    ],
  }],
  ungrouped: [],
};
const plan = {
  plan_id: "p1",
  merge_count: 1,
  group_count: 1,
  estimated_calls: 1,
  merges: [{
    source: "sram", target: "存储芯片", reason: "同义", source_count: 2, target_count: 1,
  }],
  groups: [{
    name: "存储", size: 2,
    tags: [{ tag: "存储芯片", count: 1 }, { tag: "dram", count: 1 }],
  }],
};

const calls = [];
let applied = false;
function jsonResponse(body) {
  return {
    ok: true, status: 200, statusText: "OK",
    headers: { get: () => "application/json" },
    json: async () => JSON.parse(JSON.stringify(body)),
    blob: async () => body,
  };
}
globalThis.fetch = async (url, opts = {}) => {
  const route = String(url);
  const method = (opts.method || "GET").toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : null;
  calls.push({ route, method, body });
  if (route === "/api/tags/groups" && method === "GET") {
    return jsonResponse(applied ? structureAfter : structureBefore);
  }
  if (route === "/api/tags/organize/plan" && method === "POST") return jsonResponse(plan);
  if (route === "/api/tags/organize/apply" && method === "POST") {
    applied = true;
    return jsonResponse({ plan_id: body.plan_id, report: { merged: 1 }, structure: structureAfter });
  }
  throw new Error(`unexpected fetch ${method} ${route}`);
};

/* ------------------------------------------------------------------- module */

const tags = await import(pathToFileURL(path.join(JS, "views", "tags.js")).href);
const { renderTagVocabulary, structureHtml, organizePlanHtml, acceptedSelection } = tags;
const list = documentShim.querySelector("#tag-list");

// ---- 1) pure render helpers ------------------------------------------------
const groupedHtml = structureHtml(structureBefore, escapeHtml);
assert.ok(groupedHtml.includes('data-tag-group="存储"'), "group section rendered");
assert.ok(groupedHtml.includes("存储芯片"), "group member rendered");
assert.ok(groupedHtml.includes("未分组"), "ungrouped bucket rendered");
assert.ok(groupedHtml.includes('data-organize-action="plan"'), "organize entrypoint present");
assert.ok(groupedHtml.includes('data-tag-action="merge"'), "per-tag governance preserved");

const planHtml = organizePlanHtml(
  { plan, merges: new Set(["sram"]), groups: new Set(["存储"]) }, escapeHtml);
assert.ok(planHtml.includes('data-organize-merge="sram"'), "merge row present");
assert.ok(planHtml.includes("checked"), "accepted rows start checked");
assert.ok(planHtml.includes('data-organize-group="存储"'), "group row present");
assert.ok(planHtml.includes("全部接受") && planHtml.includes("应用所选"), "actions present");

assert.deepStrictEqual(acceptedSelection(plan, new Set(), new Set()),
  { merges: [], groups: [] }, "nothing selected -> empty accepted set");
assert.deepStrictEqual(acceptedSelection(plan, new Set(["sram"]), new Set(["存储"])),
  { merges: ["sram"], groups: ["存储"] }, "accepted subset projects sources+names");

// ---- 2) grouped render → plan → reject → apply -----------------------------
await renderTagVocabulary();
assert.ok(list.innerHTML.includes('data-tag-group="存储"'), "vocab rendered by group");
assert.ok(list.innerHTML.includes("未分组"), "ungrouped tags rendered");

list.querySelectorAll("button[data-organize-action]")
  .find((b) => b.dataset.organizeAction === "plan").click();
await delay();
assert.ok(list.innerHTML.includes('data-organize-merge="sram"'), "plan review opened");

// reject the merge pair, keep the theme group
const mergeBox = list.querySelectorAll("input[data-organize-merge]")[0];
mergeBox.checked = false;
mergeBox.dispatch("change");
list.querySelectorAll("button[data-organize-action]")
  .find((b) => b.dataset.organizeAction === "apply").click();
await delay();

const applyCall = calls.filter((c) => c.route === "/api/tags/organize/apply").pop();
assert.ok(applyCall, "apply endpoint called");
assert.strictEqual(applyCall.body.plan_id, "p1");
assert.deepStrictEqual(applyCall.body.accepted.merges, [], "rejected merge excluded");
assert.deepStrictEqual(applyCall.body.accepted.groups, ["存储"], "accepted group included");
// after apply the vocabulary re-renders grouped (persisted structure)
assert.ok(list.innerHTML.includes('data-tag-group="存储"'), "grouped render after apply");
assert.ok(list.innerHTML.includes("dram"), "merged member visible after apply");
assert.ok(!list.innerHTML.includes("未分组"), "empty ungrouped bucket hidden");

console.log("tag_organize_dom: all assertions passed ✓");
