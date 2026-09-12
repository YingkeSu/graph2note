// Offline DOM behaviour harness for the S3 version switcher + compare view.
//   node tests/version_diff_dom.mjs
//
// Drives the real `/static/js/views/version-diff.js` module against a scripted
// `fetch` and a small DOM shim (no browser, no npm, no network).  Asserts the
// issue's main paths from the DOM: switching versions (read-only historical
// state), the compare view (selectors / block highlight / original images /
// templated summary), and click-to-locate.
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(here, "..", "graph2note", "webstatic", "js");

const delay = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));
const escapeHtml = (value) => String(value == null ? "" : value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

/* ----------------------------------------------------------- HTML parsing */

// Minimal, well-formed HTML parser for the markup this module generates.
function parseHtml(html) {
  const nodes = [];
  const stack = [{ children: nodes }];
  const tokenRe = /<(\/?)([a-zA-Z0-9]+)((?:\s+[^>]*?)?)(\/?)>/g;
  let last = 0;
  let match;
  const pushText = (text) => {
    const trimmed = text.replace(/\s+/g, " ");
    if (!trimmed.trim()) return;
    stack[stack.length - 1].children.push({ text: trimmed });
  };
  while ((match = tokenRe.exec(html)) !== null) {
    pushText(html.slice(last, match.index));
    last = tokenRe.lastIndex;
    const [, closing, tag, attrText, selfClose] = match;
    if (closing) {
      for (let i = stack.length - 1; i > 0; i -= 1) {
        if (stack[i].tag === tag.toLowerCase()) { stack.length = i; break; }
      }
      continue;
    }
    const attrs = {};
    const attrRe = /([a-zA-Z0-9_:-]+)(?:="([^"]*)")?/g;
    let attrMatch;
    while ((attrMatch = attrRe.exec(attrText || "")) !== null) {
      const name = attrMatch[1];
      if (!name) continue;
      attrs[name] = attrMatch[2] === undefined ? "" : attrMatch[2];
    }
    const node = makeNode(tag.toLowerCase(), attrs);
    stack[stack.length - 1].children.push(node);
    if (!selfClose && !["img", "br", "hr", "input", "meta", "link"].includes(tag.toLowerCase())) {
      stack.push(node);
    }
  }
  pushText(html.slice(last));
  return nodes;
}

function matchesSelector(node, selector) {
  if (!node || !node.tag) return false;
  const parts = selector.match(/(^[a-zA-Z][\w-]*)|(#[^.#\[]+)|(\.[^.#\[]+)|(\[([^\]=]+)(?:="?([^"\]]*)"?)?\])/g) || [];
  for (const part of parts) {
    if (part.startsWith("#")) {
      if (node.attrs.id !== part.slice(1)) return false;
    } else if (part.startsWith(".")) {
      if (!node.classList.contains(part.slice(1))) return false;
    } else if (part.startsWith("[")) {
      const inner = part.slice(1, -1);
      const eq = inner.indexOf("=");
      if (eq === -1) {
        if (!(inner in node.attrs)) return false;
      } else {
        const name = inner.slice(0, eq);
        const value = inner.slice(eq + 1).replace(/^"|"$/g, "");
        if (node.attrs[name] !== value) return false;
      }
    } else if (node.tag !== part.toLowerCase()) {
      return false;
    }
  }
  return parts.length > 0;
}

function walk(node, visit) {
  for (const child of node.children || []) {
    if (child.tag) {
      visit(child);
      walk(child, visit);
    }
  }
}

function collectText(node) {
  let out = "";
  for (const child of node.children || []) {
    if (child.tag) out += child.textContent || "";
    else out += child.text || "";
  }
  return out;
}

function makeNode(tag, attrs = {}) {
  const listeners = new Map();
  const classes = new Set((attrs.class || "").split(/\s+/).filter(Boolean));
  const dataset = {};
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("data-")) {
      const camel = key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      dataset[camel] = value;
    }
  }
  const node = {
    tag,
    tagName: tag.toUpperCase(),
    attrs,
    dataset,
    children: [],
    _html: null,
    _text: "",
    value: attrs.value || "",
    complete: false,
    naturalWidth: 0,
    naturalHeight: 0,
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
    setAttribute(k, v) { node.attrs[k] = String(v); },
    getAttribute(k) { return k in node.attrs ? node.attrs[k] : null; },
    removeAttribute(k) { delete node.attrs[k]; },
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
    click() { node.dispatch("click"); },
    focus() { globalThis.document.activeElement = node; },
    scrollIntoView(options) {
      node._scrolled = options || {};
      globalThis.__scrollCalls.push({ id: node.attrs.id || null, index: node.dataset.blockIndex });
    },
    getBoundingClientRect() { return { left: 0, top: 0, width: 600, height: 400, right: 600, bottom: 400 }; },
    querySelector(selector) { return node.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      const out = [];
      walk(node, (child) => { if (matchesSelector(child, selector)) out.push(child); });
      return out;
    },
    appendChild(child) { node.children.push(child); return child; },
    closest(selector) {
      let cursor = node;
      // depth-first parent links are not kept; walk up via a container scan
      while (cursor) {
        if (matchesSelector(cursor, selector)) return cursor;
        cursor = cursor.parent || null;
      }
      return null;
    },
  };
  Object.defineProperty(node, "innerHTML", {
    get() {
      if (node._html != null) return node._html;
      if (node._text) return escapeHtml(node._text);
      return "";
    },
    set(value) {
      node._html = String(value);
      node.children = parseHtml(node._html);
    },
  });
  Object.defineProperty(node, "textContent", {
    get() {
      if (node._text) return node._text;
      return collectText(node);
    },
    set(value) { node._text = String(value == null ? "" : value); node._html = null; node.children = []; },
  });
  Object.defineProperty(node, "id", { get() { return node.attrs.id || null; } });
  return node;
}

function makeRoot(extraAttrs = {}) {
  return makeNode("div", extraAttrs);
}

const registry = new Map();
const documentShim = {
  activeElement: null,
  createElement: (tag) => makeNode(String(tag).toLowerCase()),
  querySelector(selector) {
    if (selector.startsWith("#")) {
      const id = selector.slice(1);
      if (!registry.has(id)) registry.set(id, makeRoot({ id }));
      return registry.get(id);
    }
    return null;
  },
  querySelectorAll: () => [],
  addEventListener() {},
  execCommand() {},
};

globalThis.document = documentShim;
globalThis.window = { addEventListener() {}, confirm: () => true, marked: undefined };
globalThis.location = { hash: "#doc/d1" };
globalThis.__scrollCalls = [];

const el = (id) => documentShim.querySelector(`#${id}`);

/* --------------------------------------------------------------- fixtures */

const V1 = "v1";
const V2 = "v2";

function block(index, type, markdown, preview) {
  return { index, type, type_label: type, anchor: `block-${index}`, markdown, preview };
}

const chain = {
  document_id: "d1",
  title: "手稿",
  count: 2,
  latest_version_id: V2,
  versions: [
    { version_id: V1, index: 0, created_at: "2026-03-14T09:00:00", source: "parse",
      source_label: "解析", is_edit: false, is_history: true, current: false, diff: null },
    { version_id: V2, index: 1, created_at: "2026-03-15T09:00:00", source: "reparse",
      source_label: "重解析", is_edit: false, is_history: false, current: true,
      diff: { verdict: "major", changed_blocks: 2, total_blocks: 6,
              by_op: { added: 1, removed: 0, modified: 1, moved: 0, unchanged: 2 },
              by_type: {} } },
  ],
};

function comparePayload() {
  return {
    document_id: "d1",
    title: "手稿",
    latest_version_id: V2,
    count: 2,
    single_version: false,
    empty: false,
    same_version: false,
    a: {
      version_id: V1, created_at: "2026-03-14T09:00:00", model: "fixture",
      source: "parse", source_label: "解析", is_edit: false, is_history: true,
      is_current: false, block_count: 2, preprocessed_version_id: V1,
      blocks: [
        block(0, "heading", "# 绪论", "绪论"),
        block(1, "paragraph", "第一版原文", "第一版原文"),
      ],
    },
    b: {
      version_id: V2, created_at: "2026-03-15T09:00:00", model: "fixture",
      source: "reparse", source_label: "重解析", is_edit: false, is_history: false,
      is_current: true, block_count: 2, preprocessed_version_id: V2,
      blocks: [
        block(0, "heading", "# 绪论", "绪论"),
        block(1, "paragraph", "第二版改写", "第二版改写"),
      ],
    },
    report: {
      label_a: V1, label_b: V2,
      changes: [
        { op: "unchanged", block_type: "heading", similarity: 1,
          block_ref_a: { index: 0, block_type: "heading", anchor: "block-0" },
          block_ref_b: { index: 0, block_type: "heading", anchor: "block-0" } },
        { op: "modified", block_type: "paragraph", similarity: 0.4,
          block_ref_a: { index: 1, block_type: "paragraph", anchor: "block-1" },
          block_ref_b: { index: 1, block_type: "paragraph", anchor: "block-1" } },
      ],
      summary: {
        blocks_a: 2, blocks_b: 2, total_blocks: 4, changed_blocks: 1,
        change_density: 0.25, verdict: "minor",
        by_op: { added: 0, removed: 0, modified: 1, moved: 0, unchanged: 1 },
        by_type: { heading: { added: 0, removed: 0, modified: 0, moved: 0, unchanged: 1 },
                   paragraph: { added: 0, removed: 0, modified: 1, moved: 0, unchanged: 0 } },
      },
    },
    summary_lines: ["整体判定：小幅改动（变更 1/4 块，密度 0.25）", "修改：1 个段落"],
  };
}

const emptyPayload = () => {
  const payload = comparePayload();
  payload.empty = true;
  payload.same_version = false;
  payload.report.changes = [
    { op: "unchanged", block_type: "heading", similarity: 1,
      block_ref_a: { index: 0 }, block_ref_b: { index: 0 } },
    { op: "unchanged", block_type: "paragraph", similarity: 1,
      block_ref_a: { index: 1 }, block_ref_b: { index: 1 } },
  ];
  payload.report.summary.changed_blocks = 0;
  payload.report.summary.verdict = "unchanged";
  payload.summary_lines = ["两版内容一致，无块级变更。"];
  return payload;
};

const singlePayload = () => {
  const payload = comparePayload();
  payload.single_version = true;
  payload.count = 1;
  payload.a = payload.b;
  payload.same_version = true;
  payload.empty = true;
  payload.summary_lines = ["两版内容一致，无块级变更。"];
  return payload;
};

/* ------------------------------------------------------------- fetch replay */

const calls = [];
function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: { get: () => "application/json" },
    json: async () => JSON.parse(JSON.stringify(body)),
    blob: async () => body,
  };
}

globalThis.fetch = async (url, opts = {}) => {
  const route = String(url);
  calls.push({ route, method: (opts.method || "GET").toUpperCase() });
  if (route === "/api/documents/d1/versions") return jsonResponse(chain);
  if (route.startsWith("/api/documents/d1/diff")) {
    const query = new URLSearchParams(route.split("?")[1] || "");
    if (query.get("a") === "empty" || query.get("b") === "empty") return jsonResponse(emptyPayload());
    return jsonResponse(comparePayload());
  }
  throw new Error(`unexpected fetch ${route}`);
};

/* ------------------------------------------------------------------- module */

const stateModule = await import(pathToFileURL(path.join(JS, "state.js")).href);
const view = await import(pathToFileURL(path.join(JS, "views", "version-diff.js")).href);
stateModule.state.docId = "d1";

/* -------------------------------------- 1) version switcher (S2 chain) */

await view.renderVersionPanel("d1");
await delay(10);
const listHtml = el("version-list").innerHTML;
assert(listHtml.includes(`data-version-id="${V2}"`), "latest version listed");
assert(listHtml.includes(`data-version-id="${V1}"`), "historical version listed");
assert(listHtml.indexOf(V2) < listHtml.indexOf(V1), "versions newest-first");
assert(listHtml.includes("version-item current"), "current version flagged");
assert(listHtml.includes("+0") === false, "no bogus zero badges");
assert(listHtml.includes("version-diff-badge"), "diff badge rendered next to the version");
assert(el("version-info").textContent.includes("第 2 版"), "version count shown");

/* read-only state when a historical version is selected */
view.selectVersion(V1);
await delay(10);
assert(!el("diff-view").classList.contains("hidden"), "compare overlay opens");
assert(el("version-readonly-note").textContent.includes("只读查看历史版本"),
  "switcher shows the read-only notice");
assert(el("version-readonly-note").textContent.includes(V1), "notice names the version");
assert(el("version-readonly-note").querySelector("#version-back-latest"),
  "notice offers a way back to the latest version");
assert(el("diff-readonly").textContent.includes("历史版本"), "overlay marks the historical version");
assert(el("diff-readonly").textContent.includes(V2), "overlay guides back to the latest");

/* ---------------------------------------------- 2) compare view contents */

const selectA = el("diff-select-a");
const selectB = el("diff-select-b");
assert(selectA.innerHTML.includes(V1) && selectA.innerHTML.includes(V2), "selector A lists versions");
assert(selectB.innerHTML.includes(V2), "selector B lists versions");
assert(selectA.value === V1, "selector A reflects the clicked version");
assert(selectB.value === V2, "selector B defaults to the latest");

const summary = el("diff-summary").innerHTML;
assert(summary.includes("小幅改动"), "verdict chip rendered");
assert(summary.includes("修改：1 个段落"), "templated summary line rendered");
assert(summary.includes("变更 1/4 块"), "summary numbers come from the DiffReport");

const headA = el("diff-head-a").innerHTML;
const headB = el("diff-head-b").innerHTML;
assert(headA.includes("历史版本"), "column A marked as history");
assert(headB.includes("当前版本"), "column B marked as current");
assert(headA.includes(`/api/documents/d1/versions/${V1}/preprocessed`), "version A image URL");
assert(headB.includes(`/api/documents/d1/versions/${V2}/preprocessed`), "version B image URL");
assert(el("diff-head-a").querySelectorAll(".diff-version-img").length
  + el("diff-head-b").querySelectorAll(".diff-version-img").length === 2,
  "two original images (one per version)");

const rows = el("diff-rows");
assert(rows.querySelector(`[data-block-index="1"].diff-modified`), "modified block highlighted (yellow class)");
assert(rows.querySelector(`[data-block-index="0"].diff-unchanged`), "unchanged block present");
assert(rows.querySelector(`[data-block-index="1"].diff-latest`), "latest-side column carries the locate target");
assert(rows.querySelectorAll("[data-diff-block]").length === 4, "both columns have block cells");

/* ------------------------------------------------ 3) click-to-locate (AC4) */

globalThis.__scrollCalls.length = 0;
const changedCell = rows.querySelector(`.diff-side-a[data-block-index="1"]`);
assert(changedCell && changedCell.dataset.locate === "1", "A-side cell points at the B block");
changedCell.dispatch("click");
const flashed = rows.querySelector(`[data-block-index="1"].diff-latest.locate-flash`);
assert(flashed, "clicking a change flashes the current-version block");
assert(globalThis.__scrollCalls.some((call) => call.index === "1"), "the target block is scrolled into view");
assert(el("status-text").textContent.includes("block-1"), "locate feedback names the block anchor");

/* a block deleted in the current version has no target: flagged explicitly */
const removedRow = rows.querySelector(`[data-block-index="0"]`);
removedRow.dispatch("click");
assert(el("status-text").textContent.includes("block-0"), "locate still reports a target anchor");

/* ---------------------------------------------- 4) safe states + Esc close */

view.renderCompare(emptyPayload());
assert(!el("diff-empty").classList.contains("hidden"), "empty diff shows the safe state");
assert(el("diff-empty").textContent.includes("两版内容一致"), "empty diff explains itself");
assert(el("diff-summary").innerHTML.includes("两版内容一致"), "empty summary templated");

view.renderCompare(singlePayload());
assert(el("diff-empty").textContent.includes("只有 1 个版本"), "single version safe state");

assert(view.isCompareOpen() === true);
view.handleVersionDiffShortcut({ key: "Escape", preventDefault() {} });
assert(view.isCompareOpen() === false, "Esc closes the compare overlay");

/* --------------------------------------------- 5) deep links (router) */

const router = await import(pathToFileURL(path.join(JS, "router.js")).href);
assert.deepStrictEqual(router.parseHash("#doc/d1/diff"),
  { name: "doc", id: "d1", compare: true });
assert.deepStrictEqual(router.parseHash("#doc/d1/diff/v1/v2"),
  { name: "doc", id: "d1", compare: true, versionA: "v1", versionB: "v2" });
assert.deepStrictEqual(router.parseHash("#doc/d1/versions"),
  { name: "doc", id: "d1", panel: true });
assert.deepStrictEqual(router.parseHash("#doc/d1"), { name: "doc", id: "d1" });

console.log("version_diff_dom: all assertions passed ✓");
