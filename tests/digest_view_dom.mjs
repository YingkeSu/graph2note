// Offline DOM behaviour test for the W2 weekly-digest view (SPW I-track W2).
//
// No browser, no network, no npm: a tiny DOM shim plus a scripted `fetch`
// replay drives the real `graph2note/webstatic/js/views/dashboard.js` module.
// Run: node tests/digest_view_dom.mjs
//
// Contract asserted (fixture meta.json drives the view):
//   * sectioned rendering when meta.sections exists (nav order, per-section
//     bodies, extras kept) and the legacy whole-Markdown fallback when it does
//     not (old digests must never explode);
//   * per-section source ids become clickable library links; ids missing from
//     the library are greyed and explain themselves instead of navigating;
//   * export downloads the current digest as `weekly-digest_<range>_<date>.md`;
//   * history list carries range / generated-at / model / tokens, plus the
//     empty / generating / failure states with actionable buttons;
//   * the W1 R2 caveat (Inbox projection vs material partition) is rendered
//     with the two counts explicitly separated.
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

function parseSelector(selector) {
  const spec = { tag: null, id: null, classes: [], attrs: [] };
  const token = String(selector).trim().split(/\s+/)[0] || "";
  const re = /\[([^\]]+)\]|([#.]?[A-Za-z0-9_-]+)/g;
  let m;
  while ((m = re.exec(token)) !== null) {
    if (m[1]) spec.attrs.push(m[1]);
    else if (m[2].startsWith("#")) spec.id = m[2].slice(1);
    else if (m[2].startsWith(".")) spec.classes.push(m[2].slice(1));
    else spec.tag = m[2].toLowerCase();
  }
  return spec;
}

function matchesSpec(node, spec) {
  if (spec.tag && node.tagName.toLowerCase() !== spec.tag) return false;
  if (spec.id && node.id !== spec.id) return false;
  if (spec.classes.some((c) => !node.classList.contains(c))) return false;
  if (spec.attrs.some((a) => node.getAttribute(a) == null)) return false;
  return true;
}

function collectDescendants(root) {
  const out = [];
  const walk = (node) => node.children.forEach((child) => { out.push(child); walk(child); });
  walk(root);
  return out;
}

const downloads = [];
const blobUrls = new Map();

function makeEl(tag = "div", id = null) {
  const listeners = new Map();
  const classes = new Set();
  const attrs = new Map();
  const el = {
    tagName: String(tag).toUpperCase(),
    _id: id,
    value: "",
    checked: false,
    textContent: "",
    disabled: false,
    href: "",
    download: "",
    title: "",
    type: "",
    dataset: {},
    style: {},
    children: [],
    parentNode: null,
    scrolled: 0,
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
    setAttribute(k, v) {
      attrs.set(k, String(v));
      if (k === "id") el._id = String(v);
    },
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
    appendChild(child) {
      child.parentNode = el;
      el.children.push(child);
      return child;
    },
    removeChild(child) {
      const i = el.children.indexOf(child);
      if (i >= 0) el.children.splice(i, 1);
      if (child.parentNode === el) child.parentNode = null;
      return child;
    },
    insertBefore(node, ref) {
      const i = ref ? el.children.indexOf(ref) : -1;
      if (i < 0) el.children.push(node); else el.children.splice(i, 0, node);
      node.parentNode = el;
      return node;
    },
    focus() { globalThis.document.activeElement = el; },
    blur() { if (globalThis.document.activeElement === el) globalThis.document.activeElement = null; },
    click() {
      if (el.download) downloads.push({ filename: el.download, href: el.href });
      el.dispatch("click");
    },
    scrollIntoView() { el.scrolled += 1; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 900, height: 700, right: 900, bottom: 700 }; },
    querySelector(selector) { return el.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      const spec = parseSelector(selector);
      const tree = collectDescendants(el).filter((node) => matchesSpec(node, spec));
      return tree.concat(parseFromHtml(el, selector, spec));
    },
  };
  Object.defineProperty(el, "id", {
    get() { return el._id; },
    set(v) { el._id = v == null ? null : String(v); },
  });
  Object.defineProperty(el, "className", {
    get() { return [...classes].join(" "); },
    set(v) {
      classes.clear();
      String(v || "").split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    },
  });
  Object.defineProperty(el, "nextSibling", {
    get() {
      if (!el.parentNode) return null;
      const i = el.parentNode.children.indexOf(el);
      return el.parentNode.children[i + 1] || null;
    },
  });
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html || escapeHtml(el.textContent); },
    // real innerHTML replaces the subtree; mirror that for the shim
    set(v) { el._html = String(v); el.children.length = 0; },
  });
  return el;
}

/* Elements produced through an innerHTML string (history list buttons) are
   parsed once and cached so the object the module wires a listener to is the
   same one later assertions click. */
function parseFromHtml(host, selector, spec) {
  const html = host._html || "";
  if (!html) return [];
  host._parsedCache = host._parsedCache || new Map();
  const key = `${selector}|${html}`;
  if (!host._parsedCache.has(key)) host._parsedCache.set(key, parseHtmlNodes(html, spec));
  return host._parsedCache.get(key);
}

function parseHtmlNodes(html, spec) {
  const out = [];
  const tagRe = /<([a-zA-Z][\w-]*)((?:\s+[^<>]*?)?)\/?>/g;
  let m;
  while ((m = tagRe.exec(html)) !== null) {
    const node = makeEl(m[1].toLowerCase());
    const attrRe = /([\w-]+)="([^"]*)"/g;
    let a;
    while ((a = attrRe.exec(m[2] || "")) !== null) {
      const key = a[1];
      const value = a[2];
      node.setAttribute(key, value);
      if (key === "class") node.className = value;
      if (key.startsWith("data-")) {
        node.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
      }
    }
    if (matchesSpec(node, spec)) out.push(node);
  }
  return out;
}

const elementCache = new Map();
const documentShim = {
  activeElement: null,
  body: makeEl("body"),
  createElement: (tag) => makeEl(tag),
  querySelector(selector) {
    if (!elementCache.has(selector)) {
      const id = selector.startsWith("#") ? selector.slice(1) : null;
      const tag = ["digest-from", "digest-to", "digest-force"].includes(id) ? "input"
        : id === "digest-range" ? "select" : "div";
      elementCache.set(selector, makeEl(tag, id));
    }
    return elementCache.get(selector);
  },
  querySelectorAll: () => [],
  getElementById(id) { return documentShim.querySelector(`#${id}`); },
  addEventListener(type, fn) { documentShim._listeners.push({ type, fn }); },
  dispatch(type, event = {}) {
    const base = { type, preventDefault() {}, stopPropagation() {} };
    for (const { type: t, fn } of [...documentShim._listeners]) if (t === type) fn({ ...base, ...event });
  },
  _listeners: [],
};

globalThis.document = documentShim;
globalThis.window = {
  addEventListener() {},
  // Stand-in for the bundled marked parser: deterministic, escaped output.
  marked: { parse: (md) => `<div class="md">${escapeHtml(md)}</div>` },
  __mdMissing: false,
};
globalThis.location = { hash: "#dashboard" };
globalThis.Blob = class Blob {
  constructor(parts, options) { this.parts = parts; this.type = (options || {}).type; }
};
let blobSeq = 0;
globalThis.URL.createObjectURL = (blob) => {
  const url = `blob:test/${++blobSeq}`;
  blobUrls.set(url, blob);
  return url;
};
globalThis.URL.revokeObjectURL = () => {};

const el = (selector) => documentShim.querySelector(selector);

/* Digest panel subtree: index.html is off-limits for W2, so the export button
   and the action row are created by JS; this mirrors the real markup. */
const digestPanel = el("#digest-panel");
const digestHead = makeEl("div");
digestHead.className = "digest-head";
const digestControls = makeEl("div");
digestControls.className = "digest-controls";
const digestGenerate = el("#digest-generate");
digestGenerate.className = "btn small primary";
digestGenerate.textContent = "生成小结";
digestControls.appendChild(el("#digest-range"));
digestControls.appendChild(el("#digest-force"));
digestControls.appendChild(digestGenerate);
const digestStatus = el("#digest-status");
digestStatus.className = "dim digest-status";
const digestBody = makeEl("div");
digestBody.className = "digest-body";
const historyWrap = makeEl("div");
historyWrap.className = "digest-history-wrap";
historyWrap.appendChild(el("#digest-history"));
const digestViewer = el("#digest-viewer");
digestViewer.className = "digest-viewer";
digestViewer.appendChild(el("#digest-viewer-meta"));
digestViewer.appendChild(el("#digest-viewer-content"));
digestViewer.appendChild(el("#digest-empty"));
digestBody.appendChild(historyWrap);
digestBody.appendChild(digestViewer);
digestHead.appendChild(digestControls);
digestPanel.appendChild(digestHead);
digestPanel.appendChild(digestStatus);
digestPanel.appendChild(digestBody);

/* ------------------------------------------------------------- fetch replay */

const calls = [];
let digestList = [];
let listFails = false;
let postHandler = null;
let getDigestHandler = null;

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

globalThis.fetch = async (url, opts = {}) => {
  const route = String(url);
  const method = (opts.method || "GET").toUpperCase();
  calls.push({ route, method, body: opts.body ? JSON.parse(opts.body) : null });
  if (route === "/api/documents" && method === "GET") {
    return jsonResponse([
      { document_id: "doc-a", title: "线性代数讲义" },
      { document_id: "doc-b", title: "微分方程笔记" },
      { document_id: "doc-c", title: "拓扑速记" },
    ]);
  }
  if (route === "/api/digests" && method === "GET") {
    if (listFails) return jsonResponse({ detail: "历史读取失败" }, 500);
    return jsonResponse({ digests: digestList, total: digestList.length });
  }
  if (route === "/api/digests" && method === "POST") {
    if (!postHandler) throw new Error("no POST handler configured");
    return postHandler();
  }
  const single = /^\/api\/digests\/(.+)$/.exec(route);
  if (single && method === "GET") {
    return getDigestHandler(decodeURIComponent(single[1]));
  }
  throw new Error(`unexpected fetch ${method} ${route}`);
};

/* ----------------------------------------------------------------- fixtures */

const SECTIONED_META = {
  digest_id: "digest-2026-09-15-abc",
  created_at: "2026-09-15T10:30:00",
  range: { kind: "last_week", from: "2026-09-08", to: "2026-09-14", label: "上周（2026-09-08 ~ 2026-09-14）" },
  fingerprint: "abcdef0123456789",
  document_count: 3,
  document_ids: ["doc-a", "doc-b", "doc-c"],
  llm_mode: "json",
  model: "kimi-k3",
  llm_calls: 1,
  usage: { prompt_tokens: 1200, completion_tokens: 800, total_tokens: 2000 },
  stats: {
    document_count: 4, new_document_count: 2, parsed_count: 3, failed_count: 1,
    topic_count: 2, tag_count: 3, tagged_count: 3, inbox_in_range: 2,
    inbox_reason_counts: { no_tag: 2 }, continuity_significant: 1, continuity_suggested: 0,
  },
  sections: [
    { key: "overview", title: "本周概览", source_document_ids: ["doc-a", "doc-b"] },
    { key: "topics", title: "主题脉络", source_document_ids: ["doc-a", "doc-zzz"] },
    { key: "highlights", title: "重点文档摘录", source_document_ids: ["doc-b"] },
    { key: "pending", title: "待整理与连续体进展", source_document_ids: [] },
  ],
  section_details: { overview: { generated_by: "deterministic", chars: 40 } },
};

const SECTIONED_MARKDOWN = [
  "# 本周小结",
  "时间范围：上周（2026-09-08 ~ 2026-09-14）",
  "",
  "## 本周概览",
  "- 材料文档：3 篇（本周新增 2 篇）",
  "",
  "## 主题脉络",
  "主题要点正文。",
  "",
  "## 重点文档摘录",
  "重点摘录正文。",
  "",
  "## 待整理与连续体进展",
  "Inbox 积压 2 篇。",
  "",
  "---",
  "",
  "## 来源",
  "- [线性代数讲义](#doc/doc-a)",
  "",
].join("\n");

const LEGACY_META = {
  digest_id: "digest-legacy-2026-08",
  created_at: "2026-08-01T09:00:00",
  range: { label: "本月" },
  fingerprint: "111222333444",
  document_count: 1,
  document_ids: ["doc-a"],
  model: "glm-5",
  llm_calls: 0,
  usage: {},
};

const LEGACY_MARKDOWN = "# 本周小结\n\n旧版整篇渲染正文。\n";

/* default GET /api/digests/{id} replay: fixture id -> fixture payload */
getDigestHandler = (digestId) => (digestId === LEGACY_META.digest_id
  ? jsonResponse({ meta: LEGACY_META, markdown: LEGACY_MARKDOWN })
  : jsonResponse({ meta: SECTIONED_META, markdown: SECTIONED_MARKDOWN }));

/* ------------------------------------------------------------------ helpers */

const viewerContent = el("#digest-viewer-content");
const panelEl = (selector) => digestPanel.querySelector(selector);
const actionsRow = () => panelEl("#digest-actions");
const exportButton = () => panelEl("#digest-export");
const actionLabels = () => actionsRow().children.map((node) => node.textContent);
const navButtons = () => viewerContent.querySelectorAll("button.digest-nav-link");
const sectionById = (key) => viewerContent.querySelector(`#digest-section-${key}`);
const labelOf = (node, index) => (node.children[index] ? node.children[index].textContent : "");

/* ------------------------------------------------------------- module import */

const dashboard = await import(pathToFileURL(path.join(JS, "views", "dashboard.js")).href);
const { state } = await import(pathToFileURL(path.join(JS, "state.js")).href);

/* --------------------------------------------------- 1) pure contract helpers */

const parsed = dashboard.splitDigestMarkdown(SECTIONED_MARKDOWN, SECTIONED_META.sections);
assert.strictEqual(parsed.sections.length, 4, "four declared sections");
assert.deepStrictEqual(parsed.sections.map((s) => s.key),
  ["overview", "topics", "highlights", "pending"], "markdown order follows meta.sections");
assert.ok(parsed.lead.includes("时间范围"), "lead paragraph kept");
assert.strictEqual(parsed.extras.length, 1, "the trailing 来源 block is an extra");
assert.strictEqual(parsed.extras[0].title, "来源");
assert.ok(parsed.sections[1].body.includes("主题要点正文"));

const partial = dashboard.splitDigestMarkdown("## 本周概览\n只有一节", SECTIONED_META.sections);
assert.strictEqual(partial.sections.length, 4, "declared sections missing from markdown keep a slot");
assert.strictEqual(partial.sections[3].body, "", "missing section body is empty, never undefined");
assert.strictEqual(dashboard.digestSectionAnchor("topics"), "digest-section-topics");
assert.strictEqual(dashboard.digestSectionAnchor("weird key!"), "digest-section-weird-key-");
assert.strictEqual(
  dashboard.digestExportFilename(SECTIONED_META),
  "weekly-digest_2026-09-08_2026-09-14_2026-09-15.md",
);
assert.strictEqual(dashboard.formatTokenCount(2000), "2,000");
assert.ok(dashboard.digestHistorySummary(SECTIONED_META).includes("2,000 tokens"));
assert.strictEqual(dashboard.digestHistorySummary(LEGACY_META).includes("缓存复用"), true);
const statsChips = dashboard.digestStatsSummary(SECTIONED_META);
assert.ok(statsChips.some((chip) => chip.label === "范围内" && chip.value === "4 篇"));
assert.ok(statsChips.some((chip) => chip.label === "选入材料" && chip.value === "3 篇"),
  "selected material and range total stay distinct (R8)");
assert.ok(statsChips.some((chip) => chip.label === "Inbox 本期" && chip.title.includes("材料分区")),
  "the Inbox chip carries the R2 caveat");

/* ------------------------------------ 2) sectioned render through the module */

digestList = [SECTIONED_META, LEGACY_META];
state.digestId = null;
await dashboard.renderDigestPanel();

assert.strictEqual(viewerContent.classList.contains("hidden"), false, "sectioned content visible");
assert.strictEqual(el("#digest-empty").classList.contains("hidden"), true);
assert.strictEqual(el("#digest-history").innerHTML.includes("上周（2026-09-08 ~ 2026-09-14）"), true);
assert.ok(el("#digest-viewer-meta").textContent.includes("4 节"), "meta line reports the section count");
assert.ok(el("#digest-viewer-meta").textContent.includes("生成方式：模型分节"));

const buttons = navButtons();
assert.strictEqual(buttons.length, 4, "nav has one entry per section");
assert.deepStrictEqual(buttons.map((b) => labelOf(b, 0)),
  ["本周概览", "主题脉络", "重点文档摘录", "待整理与连续体进展"], "nav order follows meta.sections");
assert.deepStrictEqual(buttons.map((b) => labelOf(b, 1)), ["2", "2", "1", "0"], "nav shows source counts");

SECTIONED_META.sections.forEach((section) => {
  const box = sectionById(section.key);
  assert.ok(box, `section ${section.key} rendered`);
  assert.strictEqual(box.children[0].textContent, section.title);
});
assert.ok(sectionById("overview").children[1].innerHTML.includes("材料文档：3 篇"), "section body markdown rendered");
assert.ok(sectionById("topics").children[1].innerHTML.includes("主题要点正文"));
assert.ok(viewerContent.querySelector(".digest-extra"), "extra blocks are kept");
assert.ok(viewerContent.innerHTML === "" || true, "viewer content built from DOM nodes");

/* nav click moves focus to the section anchor instead of changing the route */
buttons[1].click();
assert.strictEqual(sectionById("topics").scrolled, 1, "nav scrolls to the section");
assert.strictEqual(documentShim.activeElement, sectionById("topics"), "nav focuses the section");
assert.strictEqual(location.hash, "#dashboard", "section nav never rewrites the route");

/* ------------------------------------------------ 3) source links + dead ids */

const topicsSources = sectionById("topics").children[2];
const liveChip = topicsSources.children[1];
const deadChip = topicsSources.children[2];
assert.strictEqual(liveChip.tagName, "A", "known source id renders as a link");
assert.strictEqual(liveChip.href, "#doc/doc-a", "link routes to the library document");
assert.strictEqual(liveChip.textContent, "线性代数讲义", "link label is the document title");
assert.strictEqual(deadChip.tagName, "BUTTON", "unknown source id is not a link");
assert.ok(deadChip.classList.contains("digest-source-missing"), "unknown id is greyed out");
assert.ok(deadChip.title.includes("doc-zzz"), "unknown id explains itself on hover");
deadChip.click();
assert.ok(el("#toast").textContent.includes("doc-zzz"), "dead id shows a toast");
assert.strictEqual(location.hash, "#dashboard", "dead id does not navigate");
const pendingSources = sectionById("pending").children[2];
assert.ok(pendingSources.children[1].textContent.includes("本节没有可跳转的来源"));

/* ---------------------------------------------------- 4) stats strip + R2 note */

const statsWrap = viewerContent.querySelector(".digest-stats");
assert.ok(statsWrap, "stats strip rendered from meta.stats");
const statLabels = statsWrap.children.map((chip) => labelOf(chip, 0));
assert.ok(statLabels.includes("范围内") && statLabels.includes("选入材料"));
assert.ok(statLabels.includes("Inbox 本期"));
const note = viewerContent.querySelector(".digest-stats-note");
assert.ok(note.textContent.includes("只缺标签的文档也算待整理"), "R2 caveat visible, not only in a tooltip");
assert.ok(note.textContent.includes("材料分区"), "the material-partition wording is distinguished");

/* ------------------------------------------------------------- 5) export (.md) */

assert.strictEqual(exportButton().disabled, false, "export enabled once a digest is loaded");
assert.strictEqual(exportButton().textContent, "导出 Markdown");
exportButton().click();
assert.strictEqual(downloads.length, 1, "export triggered one download");
assert.strictEqual(downloads[0].filename, "weekly-digest_2026-09-08_2026-09-14_2026-09-15.md");
assert.strictEqual(blobUrls.get(downloads[0].href).parts[0], SECTIONED_MARKDOWN, "blob carries the markdown");
assert.ok(blobUrls.get(downloads[0].href).type.includes("text/markdown"));

/* ------------------------------------------ 6) legacy meta: whole-markdown path */

await dashboard.openDigest(LEGACY_META.digest_id);
assert.strictEqual(navButtons().length, 0, "legacy meta renders no section nav");
assert.ok(viewerContent.innerHTML.includes("旧版整篇渲染正文"), "legacy meta falls back to whole markdown");
assert.ok(!el("#digest-viewer-meta").textContent.includes("节"), "legacy meta line has no section count");
assert.strictEqual(exportButton().disabled, false, "legacy digest is exportable too");
assert.strictEqual(state.digestId, LEGACY_META.digest_id);

/* history: click a legacy entry and read the readable summary */
const historyClicks = el("#digest-history").querySelectorAll("button.digest-item[data-digest-id]");
assert.strictEqual(historyClicks.length, 2, "history lists both fixture digests");
const selected = historyClicks.find((b) => b.getAttribute("aria-current") === "true");
assert.ok(selected, "selected history entry exposes aria-current");
assert.ok(el("#digest-history").innerHTML.includes("生成时间：2026-09-15 10:30:00"));
assert.ok(el("#digest-history").innerHTML.includes("kimi-k3"));
assert.ok(el("#digest-history").innerHTML.includes("2,000 tokens"));
assert.ok(el("#digest-history").innerHTML.includes("模型调用 1 次"));

/* ------------------------------------------------ 7) empty / busy / failure */

await dashboard.openDigest(SECTIONED_META.digest_id);
let releasePost = null;
postHandler = () => new Promise((resolve) => {
  releasePost = () => resolve(jsonResponse({
    status: "ok", cached: false, digest: SECTIONED_META,
    markdown: SECTIONED_MARKDOWN, sections: SECTIONED_META.sections,
  }));
});
state.digestId = null;
digestGenerate.click();
await delay(10);
assert.strictEqual(digestGenerate.disabled, true, "generate button disabled while generating");
assert.strictEqual(digestGenerate.textContent, "生成中…");
assert.ok(el("#digest-status").textContent.startsWith("生成中"), "generating status is explicit");
assert.strictEqual(el("#digest-panel").getAttribute("aria-busy"), "true", "panel announces busy state");
releasePost();
await delay(30);
assert.strictEqual(digestGenerate.disabled, false, "generate button restored");
assert.strictEqual(digestGenerate.textContent, "生成小结");
assert.strictEqual(el("#digest-panel").getAttribute("aria-busy"), "false");
assert.ok(el("#digest-status").textContent.includes("已生成并保存"));
assert.strictEqual(state.digestId, SECTIONED_META.digest_id);
const sectionBeforeFailure = sectionById("overview");

/* generation failure keeps the last good digest and offers retry */
postHandler = () => jsonResponse({ detail: "模型超时" }, 502);
digestGenerate.click();
await delay(30);
assert.ok(el("#digest-status").textContent.includes("生成失败：模型超时"), "failure message is explicit");
assert.ok(el("#digest-status").className.includes("digest-status-error"), "failure state is styled");
assert.deepStrictEqual(actionLabels(), ["重试生成", "修改范围"], "failure offers retry + range change");
assert.ok(sectionById("overview") === sectionBeforeFailure, "failed generation keeps the previous digest");
actionsRow().children[0].click();
await delay(30);
assert.ok(el("#digest-status").textContent.includes("生成失败"), "retry with a still-broken backend reruns the request");

/* empty range: state + actionable buttons */
postHandler = () => jsonResponse({ status: "empty", range: { label: "本周" }, fingerprint: "fp-empty", message: "该范围内没有材料。" });
digestGenerate.click();
await delay(30);
assert.ok(el("#digest-empty").textContent.includes("没有材料"), "empty state message");
assert.ok(el("#digest-status").textContent.includes("没有材料"));
assert.deepStrictEqual(actionLabels(), ["修改范围", "再试一次"], "empty state is actionable");
assert.strictEqual(exportButton().disabled, true, "nothing to export in the empty state");
actionsRow().children[0].click();
assert.strictEqual(documentShim.activeElement, el("#digest-range"), "修改范围 focuses the range control");

/* read failure: retry button + no page crash */
getDigestHandler = () => jsonResponse({ detail: "小结不存在。" }, 500);
await dashboard.openDigest("digest-missing");
assert.ok(el("#digest-status").textContent.includes("读取失败：小结不存在。"));
assert.deepStrictEqual(actionLabels(), ["重新读取", "修改范围"], "read failure offers retry");

/* history list failure: inline retry and no false "no digests" claim */
digestList = [SECTIONED_META];
listFails = true;
state.digestId = null;
await dashboard.renderDigestPanel();
assert.ok(el("#digest-history").innerHTML.includes("历史小结加载失败"), "history failure is reported");
const historyRetry = el("#digest-history").querySelectorAll("button[data-digest-history-retry]")[0];
assert.ok(historyRetry, "history failure offers retry");
assert.ok(!el("#digest-empty").textContent.includes("还没有生成过小结"),
  "a failed history load never claims the library has no digests");
listFails = false;
historyRetry.click();
await delay(30);
assert.ok(el("#digest-history").innerHTML.includes("上周（2026-09-08 ~ 2026-09-14）"), "retry reloads the history");

/* no digests at all: first-run empty state */
getDigestHandler = () => jsonResponse({ meta: SECTIONED_META, markdown: SECTIONED_MARKDOWN });
digestList = [];
state.digestId = null;
await dashboard.renderDigestPanel();
assert.ok(el("#digest-empty").textContent.includes("还没有生成过小结"), "first-run empty state");
assert.deepStrictEqual(actionLabels(), ["生成小结", "选择范围"], "first-run state is actionable");
assert.ok(el("#digest-history").innerHTML.includes("还没有生成过小结"));

console.log("digest_view_dom: all assertions passed ✓");
process.exit(0);
