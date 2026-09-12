// Node contract test for the U5 Timeline visual view (pure functions + tiny
// fake DOM + read-only request surface).
//
// `timeline_view.js` has no imports and touches no DOM at load time, so it can
// be exercised in plain Node: trunk/tick/run-band markup, the gap markers, the
// monthly density bar, the viewport-gated thumbnail loader, the run-band
// expand/collapse state and the fact that the timeline only ever issues GETs.
// Run: node tests/timeline_view.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const modulePath = path.join(
  here, "..", "graph2note", "webstatic", "js", "timeline_view.js",
);
const timeline = await import(pathToFileURL(modulePath).href);
const {
  TIMELINE_DEFAULT_ROUTE, RUN_COLORS, topicColor, sourceIcon, gapLabel,
  timelineItemVm, timelineItemHtml, timelineGroupHtml, timelineGroupsHtml,
  runBandsHtml, densityBarsHtml, loadTimeline, createThumbnailLoader,
  toggleRunBand, wireTimeline,
} = timeline;

const escapeHtml = (value) => String(value == null ? "" : value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const item = {
  document_id: "doc-1",
  title: "状态空间模型笔记",
  date: "2026-03-04",
  effective_time: { field: "document_time", value: "2026-03-04T10:00:00", source: "inferred" },
  topics: ["数学", "控制"],
  tags: ["重点", "复习"],
  tag_count: 2,
  source_kind: "pdf",
  source_label: "lecture.pdf · 第 12 页",
  thumbnail_url: "/api/documents/doc-1/preprocessed",
  route: "#doc/doc-1",
};

// ---- 1) colour mapping is deterministic and from the palette --------------
assert.ok(RUN_COLORS.includes(topicColor("数学")));
assert.strictEqual(topicColor("数学"), topicColor("数学"));
assert.notStrictEqual(topicColor("数学"), topicColor("控制"));

// ---- 2) source icon (pdf page vs image vs document) -----------------------
assert.deepStrictEqual(sourceIcon(item),
  { kind: "pdf", icon: "📄", label: "lecture.pdf · 第 12 页" });
assert.strictEqual(sourceIcon({ source_kind: "image" }).icon, "🖼");
assert.strictEqual(sourceIcon({ source_kind: "document" }).icon, "📝");
assert.strictEqual(sourceIcon({}).kind, "image");

// ---- 3) gap markers -------------------------------------------------------
assert.strictEqual(gapLabel(12), "间隔 12 天");
assert.strictEqual(gapLabel(0), "");
assert.strictEqual(gapLabel(null), "");
assert.strictEqual(gapLabel("3"), "间隔 3 天");

// ---- 4) read-only request surface: exactly one GET, only /api/timeline ----
assert.strictEqual(TIMELINE_DEFAULT_ROUTE, "#timeline/day");
const calls = [];
const mockApi = (route, opts = {}) => {
  calls.push({ route, method: (opts.method || "GET").toUpperCase() });
  return Promise.resolve({ groups: [], undated: [], total: 0, density: [], density_max: 0 });
};
await loadTimeline(mockApi, "day");
await loadTimeline(mockApi, "week");
await loadTimeline(mockApi, "nonsense");
assert.ok(calls.every((call) => call.method === "GET"),
  "the timeline must never issue a non-GET request");
assert.deepStrictEqual(calls.map((call) => call.route), [
  "/api/timeline?group_by=day",
  "/api/timeline?group_by=week",
  "/api/timeline?group_by=day",
]);

// ---- 5) item markup: thumbnail/title/source icon/tag count/route ----------
const itemHtml = timelineItemHtml(item, escapeHtml, { index: 0, runs: [] });
assert.ok(itemHtml.includes('class="timeline-item"'), "entry button");
assert.ok(itemHtml.includes('data-route="#doc/doc-1"'), "entry route to the editor");
assert.ok(itemHtml.includes('loading="lazy"'), "native lazy hint");
assert.ok(itemHtml.includes('data-src="/api/documents/doc-1/preprocessed"'), "deferred thumbnail");
assert.ok(!/(^|\s)src="/.test(itemHtml), "no eager src attribute on the thumbnail");
assert.ok(itemHtml.includes("状态空间模型笔记"), "title");
assert.ok(itemHtml.includes('data-source-kind="pdf"'), "source icon kind");
assert.ok(itemHtml.includes("📄"), "source icon glyph");
assert.ok(itemHtml.includes("2026-03-04"), "date");
assert.ok(itemHtml.includes("数学") && itemHtml.includes("控制"), "topic chips");
assert.ok(itemHtml.includes("标签 2"), "tag count");

// escaping: untrusted title/topic never becomes markup
const escaped = timelineItemHtml(
  { document_id: "d", title: "<b>x</b>", topics: ["<i>t</i>"], route: "#doc/d" },
  escapeHtml,
);
assert.ok(!escaped.includes("<b>x</b>") && !escaped.includes("<i>t</i>"), "escaped");

// ---- 6) run bands + group markup (trunk, ticks, expand/collapse) ----------
const runs = [
  { topic: "数学", count: 2, document_ids: ["doc-1", "doc-2"], group_key: "2026-03-04" },
];
const bandHtml = runBandsHtml(runs, escapeHtml);
assert.ok(bandHtml.includes('class="timeline-run-band"'), "run band button");
assert.ok(bandHtml.includes('data-run-index="0"'), "run index");
assert.ok(bandHtml.includes('aria-expanded="false"'), "collapsed by default");
assert.ok(bandHtml.includes("展开"), "expand affordance");
assert.ok(bandHtml.includes("连续 2 份"), "run size");

const group = {
  key: "2026-03-04",
  label: "2026-03-04",
  start_date: "2026-03-04",
  end_date: "2026-03-04",
  count: 2,
  gap_days: 12,
  items: [item, { ...item, document_id: "doc-2", title: "第二份", route: "#doc/doc-2" }],
  topic_aggregates: [{ topic: "数学", count: 2, document_ids: ["doc-1", "doc-2"] }],
  adjacent_topic_runs: runs,
};
const groupHtml = timelineGroupHtml(group, escapeHtml);
assert.ok(groupHtml.includes('class="timeline-group"'), "group root");
assert.ok(groupHtml.includes('class="timeline-tick"'), "trunk tick");
assert.ok(groupHtml.includes('data-group-key="2026-03-04"'), "group key for jumping");
assert.ok(groupHtml.includes("timeline-item-row"), "entries");
assert.ok(groupHtml.includes('data-run-indices="0"'), "entries track their run");
assert.ok(!groupHtml.includes("<form"), "read-only: no forms");

// gap markers between non-touching groups; none for touching ones
const groupsHtml = timelineGroupsHtml([
  { ...group, gap_days: null },
  { ...group, key: "2026-03-16", gap_days: 12, items: [{ ...item, document_id: "doc-3" }] },
], escapeHtml);
assert.ok(groupsHtml.includes('class="timeline-gap"'), "gap marker rendered");
assert.ok(groupsHtml.includes("间隔 12 天"), "gap label");
assert.ok(!timelineGroupsHtml([{ ...group, key: "a", gap_days: 0 }, { ...group, key: "b", gap_days: 0 }], escapeHtml)
  .includes("timeline-gap"), "touching groups carry no gap marker");

// ---- 7) monthly density bar ------------------------------------------------
const densityHtml = densityBarsHtml([
  { month: "2026-02", count: 3, group_key: "2026-02-01" },
  { month: "2026-03", count: 12, group_key: "2026-03-04" },
], 12, escapeHtml);
assert.ok(densityHtml.includes('class="timeline-density-bar"'), "density bar");
assert.ok(densityHtml.includes('data-group-key="2026-03-04"'), "jump target");
assert.ok(densityHtml.includes("height:100%"), "tallest month fills the bar");
assert.ok(densityHtml.includes("height:25%"), "counts scale to the max");
assert.strictEqual(densityBarsHtml([], 0, escapeHtml), "");

// ---- 8) tiny fake DOM: toggle + navigation + density jump -----------------
class FakeElement {
  constructor(tag, { className = "", dataset = {}, attrs = {} } = {}) {
    this.tagName = tag.toUpperCase();
    this.className = className;
    this.dataset = { ...dataset };
    this.attrs = { ...attrs };
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    const classes = new Set(String(className).split(/\s+/).filter(Boolean));
    this.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle: (name, force) => {
        const next = force === undefined ? !classes.has(name) : Boolean(force);
        if (next) classes.add(name); else classes.delete(name);
        return next;
      },
      values: () => [...classes],
    };
    this._classes = classes;
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
  removeAttribute(name) { delete this.attrs[name]; }
  append(child) { child.parentNode = this; this.children.push(child); return child; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) { (this.listeners[type] || []).forEach((fn) => fn(event)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const found = [];
    const walk = (node) => node.children.forEach((child) => {
      if (matchesSelector(child, selector)) found.push(child);
      walk(child);
    });
    walk(this);
    return found;
  }
}

function matchesSelector(node, selector) {
  return selector.split(/(?=[.[])/).filter(Boolean).every((part) => {
    if (part.startsWith(".")) return node.classList.contains(part.slice(1));
    if (part.startsWith("[") && part.endsWith("]")) {
      const name = part.slice(1, -1);
      if (!name.startsWith("data-")) return false;
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return Object.prototype.hasOwnProperty.call(node.dataset, key);
    }
    return node.tagName === part.toUpperCase();
  });
}

const root = new FakeElement("div");
const groupEl = root.append(new FakeElement("section", { className: "timeline-group" }));
const bandEl = groupEl.append(new FakeElement("button", {
  className: "timeline-run-band", dataset: { runIndex: "1" }, attrs: { "aria-expanded": "false" },
}));
const bandToggle = bandEl.append(new FakeElement("span", { className: "timeline-run-toggle" }));
const row1 = groupEl.append(new FakeElement("li", {
  className: "timeline-item-row", dataset: { runIndices: "1" },
}));
const row2 = groupEl.append(new FakeElement("li", {
  className: "timeline-item-row", dataset: { runIndices: "1,2" },
}));
const row3 = groupEl.append(new FakeElement("li", {
  className: "timeline-item-row", dataset: { runIndices: "2" },
}));
const entry = new FakeElement("button", { className: "timeline-item", dataset: { route: "#doc/doc-1" } });
root.append(entry);
const densityBar = root.append(new FakeElement("button", {
  className: "timeline-density-bar", dataset: { groupKey: "2026-03-04" },
}));

const nav = [];
const jumps = [];
wireTimeline(root, { go: (route) => nav.push(route), scrollTo: (key) => jumps.push(key) });

bandEl.dispatch("click");
assert.strictEqual(bandEl.getAttribute("aria-expanded"), "true", "band expands");
assert.strictEqual(bandToggle.textContent, "收起", "toggle label flips");
assert.ok(row1.classList.contains("run-active"), "matching row highlighted");
assert.ok(row2.classList.contains("run-active"), "overlapping row highlighted");
assert.ok(!row3.classList.contains("run-active"), "non-matching row untouched");
bandEl.dispatch("click");
assert.strictEqual(bandEl.getAttribute("aria-expanded"), "false", "band collapses");
assert.ok(!row1.classList.contains("run-active"), "highlight removed");

assert.strictEqual(toggleRunBand(null), null, "toggle tolerates a missing band");

entry.dispatch("click");
assert.deepStrictEqual(nav, ["#doc/doc-1"], "entry click opens the editor route");
densityBar.dispatch("click");
assert.deepStrictEqual(jumps, ["2026-03-04"], "density bar jumps to its group");

// ---- 9) lazy loader: initial requests only cover the viewport --------------
const TOTAL = 43;
const VIEWPORT = 12;
const images = Array.from({ length: TOTAL }, (_, index) => ({
  dataset: { src: `/api/documents/d${index}/preprocessed` },
  src: "",
  getAttribute(name) { return name === "data-src" ? this.dataset.src : null; },
  setAttribute(name, value) { if (name === "src") this.src = value; },
  removeAttribute(name) { if (name === "data-src") delete this.dataset.src; },
}));
let notify = null;
const fakeObserver = {
  observe(target) {
    if (images.indexOf(target) < VIEWPORT) notify([{ isIntersecting: true, target }], fakeObserver);
  },
  unobserve() {},
  disconnect() {},
};
const loader = createThumbnailLoader({
  makeObserver: (callback) => { notify = callback; return fakeObserver; },
});
images.forEach((img) => loader.observe(img));
const loaded = images.filter((img) => img.src).length;
assert.strictEqual(loaded, VIEWPORT, `expected ${VIEWPORT} initial thumbnail requests, got ${loaded}`);
assert.strictEqual(images.slice(VIEWPORT).filter((img) => img.src).length, 0,
  "off-viewport entries must not request their thumbnail");

const fallbackImages = Array.from({ length: TOTAL }, () => ({
  getAttribute(name) { return name === "data-src" ? "/thumb" : null; },
  setAttribute(name, value) { if (name === "src") this.src = value; },
  removeAttribute() {},
}));
const fallbackLoader = createThumbnailLoader({ makeObserver: null });
fallbackImages.forEach((img) => fallbackLoader.observe(img));
assert.strictEqual(fallbackImages.filter((img) => img.src).length, TOTAL);

console.log("timeline_view: all assertions passed ✓");
