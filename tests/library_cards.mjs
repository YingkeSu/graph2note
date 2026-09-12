// Node contract test for the U2 Library cards (pure functions + tiny fake DOM).
//
// `library_cards.js` has no imports and touches no DOM at load time, so it can
// be exercised in plain Node: card markup, the viewport-gated thumbnail loader
// and click/quick-action dispatch.  Run: node tests/library_cards.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const modulePath = path.join(
  here, "..", "graph2note", "webstatic", "js", "library_cards.js",
);
const cards = await import(pathToFileURL(modulePath).href);
const {
  cardHtml, cardTitle, cardFilename, cardDate, cardDateSource, cardTags,
  cardSource, cardViewModel, createThumbnailLoader, wireCardActions,
  normalizeDensity, MAX_TAG_CHIPS,
} = cards;

const escapeHtml = (value) => String(value == null ? "" : value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const richDoc = {
  document_id: "doc-1",
  title: "IMG_2031.png",
  headline: "状态空间模型笔记",
  effective_time: { field: "document_time", value: "2026-03-04T10:00:00", source: "inferred" },
  tags: ["数学", "控制", "笔记", "额外"],
  source_kind: "pdf",
  source_pdf: "lecture.pdf",
  page_number: 12,
  source_label: "lecture.pdf · 第 12 页",
  thumbnail_url: "/api/documents/doc-1/thumbnail",
};

// ---- 1) title: Markdown headline first, filename fallback ------------------
assert.strictEqual(cardTitle({ title: "a.png", headline: "标题" }), "标题");
assert.strictEqual(cardTitle({ title: "a.png", headline: "   " }), "a.png");
assert.strictEqual(cardTitle({ title: "", document_id: "doc-9" }), "doc-9");
assert.strictEqual(cardTitle({}), "未命名文档");
assert.strictEqual(cardFilename({ title: "a.png", headline: "标题" }), "a.png");
assert.strictEqual(cardFilename({ title: "a.png", headline: "a.png" }), "");

// ---- 2) date comes from the API's effective-time selection -----------------
assert.strictEqual(cardDate(richDoc), "2026-03-04");
assert.strictEqual(cardDateSource(richDoc), "inferred");
assert.strictEqual(cardDate({ updated_at: "2026-03-04" }), "");
assert.strictEqual(cardDate({ effective_time: { value: "" } }), "");
assert.strictEqual(cardDate({}), "");

// ---- 3) tag chips: <=3 + overflow count ------------------------------------
assert.deepStrictEqual(cardTags({ tags: ["a", "b", "c", "d"] }),
  { visible: ["a", "b", "c"], overflow: 1, total: 4 });
assert.deepStrictEqual(cardTags({}), { visible: [], overflow: 0, total: 0 });
assert.strictEqual(MAX_TAG_CHIPS, 3);

// ---- 4) source icon (pdf page vs image upload) -----------------------------
assert.deepStrictEqual(cardSource(richDoc),
  { kind: "pdf", icon: "PDF", label: "lecture.pdf · 第 12 页" });
assert.strictEqual(cardSource({ source_kind: "image" }).kind, "image");
assert.strictEqual(cardSource({}).icon, "图片");

// ---- 5) density normalisation ----------------------------------------------
assert.strictEqual(normalizeDensity("comfortable"), "comfortable");
assert.strictEqual(normalizeDensity("nonsense"), "compact");
assert.strictEqual(normalizeDensity(null), "compact");

// ---- 6) card markup: lazy thumb, headline, date, chips, icon, actions ------
const html = cardHtml(richDoc, escapeHtml);
assert.ok(html.includes('class="doc-card"'), "card root");
assert.ok(html.includes('data-id="doc-1"'), "card carries the document id");
assert.ok(html.includes('data-src="/api/documents/doc-1/thumbnail"'), "thumbnail is deferred");
assert.ok(html.includes('loading="lazy"'), "native lazy hint");
assert.ok(!/(^|\s)src="/.test(html), "no eager src attribute on the thumbnail");
assert.ok(html.includes("状态空间模型笔记"), "headline is the title");
assert.ok(html.includes("IMG_2031.png"), "filename is secondary info");
assert.ok(html.includes("2026-03-04"), "effective date");
assert.ok(html.includes("#数学") && html.includes("#控制") && html.includes("#笔记"), "chips");
assert.ok(html.includes("+1"), "tag overflow count");
assert.ok(html.includes('data-source-kind="pdf"'), "source icon kind");
assert.ok(html.includes("PDF"), "source icon glyph");
assert.ok(html.includes('data-card-action="reparse"') && html.includes('data-card-action="delete"'));
assert.ok(html.includes("↻") && html.includes("✕"));

// escaping: untrusted markdown/filename never becomes markup
const escaped = cardHtml({ title: "<img src=x onerror=1>", headline: "<b>hi</b>" }, escapeHtml);
assert.ok(!escaped.includes("<b>hi</b>"), "headline escaped");
assert.ok(!escaped.includes("<img src=x"), "filename escaped");
assert.strictEqual(cardViewModel({ document_id: "d" }).tags.length, 0);

// ---- 7) lazy loader: initial requests only cover the viewport --------------
const TOTAL = 43;
const VIEWPORT = 12;
const images = Array.from({ length: TOTAL }, (_, index) => ({
  dataset: { src: `/api/documents/d${index}/thumbnail` },
  src: "",
  getAttribute(name) { return name === "data-src" ? this.dataset.src : null; },
  setAttribute(name, value) { if (name === "src") this.src = value; },
  removeAttribute(name) { if (name === "data-src") delete this.dataset.src; },
}));
let notify = null;
const fakeObserver = {
  observe(target) {
    // emulate a browser: only cards inside the viewport intersect on load
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
  "off-viewport cards must not request their thumbnail");

// degradation path: without IntersectionObserver every src is assigned
const fallbackImages = Array.from({ length: TOTAL }, () => ({
  getAttribute(name) { return name === "data-src" ? "/thumb" : null; },
  setAttribute(name, value) { if (name === "src") this.src = value; },
  removeAttribute() {},
}));
const fallbackLoader = createThumbnailLoader({ makeObserver: null });
fallbackImages.forEach((img) => fallbackLoader.observe(img));
assert.strictEqual(fallbackImages.filter((img) => img.src).length, TOTAL);

// ---- 8) card click + quick actions (tiny fake DOM) -------------------------
class FakeElement {
  constructor(tag, { className = "", dataset = {} } = {}) {
    this.tagName = tag.toUpperCase();
    this.className = className;
    this.dataset = dataset;
    this.children = [];
    this.listeners = {};
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
    this.setAttribute = () => {};
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) { (this.listeners[type] || []).forEach((fn) => fn(event)); }
  querySelectorAll(selector) {
    const matches = (node) => {
      if (selector.startsWith(".")) {
        return String(node.className || "").split(/\s+/).includes(selector.slice(1));
      }
      if (selector.startsWith("[") && selector.endsWith("]")) {
        const attr = selector.slice(1, -1);
        if (!attr.startsWith("data-")) return false;
        const key = attr.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        return node.dataset && Object.prototype.hasOwnProperty.call(node.dataset, key);
      }
      return false;
    };
    const found = [];
    const walk = (node) => node.children.forEach((child) => {
      if (matches(child)) found.push(child);
      walk(child);
    });
    walk(this);
    return found;
  }
}

const root = new FakeElement("div");
const card = new FakeElement("article", { className: "doc-card", dataset: { id: "doc-7" } });
const reparse = new FakeElement("button", { className: "doc-action", dataset: { cardAction: "reparse" } });
const remove = new FakeElement("button", { className: "doc-action danger", dataset: { cardAction: "delete" } });
card.children.push(reparse, remove);
root.children.push(card);

const calls = { open: [], remove: [], reparse: [] };
let allowDelete = true;
let allowReparse = true;
wireCardActions(root, {
  open: (id) => calls.open.push(id),
  confirmDelete: () => allowDelete,
  remove: (id) => calls.remove.push(id),
  confirmReparse: () => allowReparse,
  reparse: (id) => calls.reparse.push(id),
});
const buttonEvent = { stopPropagation() {} };

card.dispatch("click");
assert.deepStrictEqual(calls.open, ["doc-7"], "clicking a card opens the editor");
card.dispatch("keydown", { key: "Enter", preventDefault() {} });
assert.deepStrictEqual(calls.open, ["doc-7", "doc-7"], "Enter opens the editor");

allowDelete = false;
remove.dispatch("click", buttonEvent);
assert.deepStrictEqual(calls.remove, [], "cancelled delete must not remove");
allowDelete = true;
remove.dispatch("click", buttonEvent);
assert.deepStrictEqual(calls.remove, ["doc-7"], "confirmed delete removes");

allowReparse = false;
reparse.dispatch("click", buttonEvent);
assert.deepStrictEqual(calls.reparse, [], "cancelled reparse must not run");
allowReparse = true;
reparse.dispatch("click", buttonEvent);
assert.deepStrictEqual(calls.reparse, ["doc-7"], "confirmed reparse runs");

console.log("library_cards: all assertions passed ✓");
