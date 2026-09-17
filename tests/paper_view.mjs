// Node contract test for the SPW P3 paper reading view (no browser).
//
// Two DOM-free modules are exercised against a SPEC §2 fixture:
//   * paper_view_core.js — normalization + markup + library badge decoration
//   * library_cards.js   — the additive "论文" grid marker
// plus router.js for the `#paper/<id>` deeplink and the extra render hook.
// Run: node tests/paper_view.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webstatic = path.join(here, "..", "graph2note", "webstatic");
const load = (rel) => import(pathToFileURL(path.join(webstatic, rel)).href);

const core = await load("js/paper_view_core.js");
const cards = await load("js/library_cards.js");

const escapeHtml = (value) => String(value == null ? "" : value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

// ---- SPEC §2 fixture -------------------------------------------------------
const payload = {
  document_id: "paper-1",
  doc_kind: "paper",
  title: "record title fallback",
  meta: {
    title: "Attention Is All You Need",
    authors: ["Ashish Vaswani", "Noam Shazeer"],
    year: 2017,
    venue: "NeurIPS",
    doi: "10.5555/3295222.3295349",
    abstract: "The dominant sequence transduction models are based on complex recurrent networks.",
    keywords: ["transformer", "attention"],
    source: "text-layer",
  },
  sections: [
    { level: 1, title: "1 Introduction", text: "Recurrent models...", page_start: 1, page_end: 1 },
    { level: 2, title: "1.1 Background", text: "Background text", page_start: 1, page_end: 2 },
    { level: 1, title: "2 Model", text: "Most competitive neural sequence models", page_start: 3, page_end: 4 },
  ],
  references: [
    { raw: "[1] Bahdanau et al. 2015", title: "Neural Machine Translation",
      authors: ["Dzmitry Bahdanau"], year: 2015, doi: "10.3115/v1/D14-1179",
      resolved_document_id: "doc-ref-1" },
    { raw: "[2] Anonymous preprint", title: "", authors: [], year: null, doi: "",
      resolved_document_id: null, notes: ["authors-unparsed"] },
  ],
};

// ---- 1) paper gating / degradation ----------------------------------------
assert.strictEqual(core.paperDocKind(payload), "paper");
assert.strictEqual(core.isPaperView(payload), true);
assert.strictEqual(core.isPaperView({ ...payload, doc_kind: "manuscript" }), false);
assert.strictEqual(core.isPaperView({ doc_kind: "paper", sections: [] }), false,
  "a paper without sections must degrade to the standard document view");
assert.strictEqual(core.isPaperView(null), false);
assert.strictEqual(core.paperDocKind(undefined), "");

// ---- 2) normalization drops blanks, never fabricates ----------------------
const view = core.normalizePaperView(payload);
assert.strictEqual(view.meta.title, "Attention Is All You Need");
assert.deepStrictEqual(view.meta.authors, ["Ashish Vaswani", "Noam Shazeer"]);
assert.strictEqual(view.meta.year, 2017);
assert.strictEqual(view.sections.length, 3);
assert.strictEqual(view.references.length, 2);
const sparse = core.normalizePaperView({ doc_kind: "paper", sections: [{ title: "" }] });
assert.deepStrictEqual(sparse.meta.authors, []);
assert.strictEqual(sparse.meta.year, null);
assert.strictEqual(sparse.meta.abstract, "");

// ---- 3) section tree + nav items ------------------------------------------
const nav = core.sectionNavItems(payload.sections);
assert.deepStrictEqual(nav.map((item) => [item.title, item.depth]),
  [["1 Introduction", 0], ["1.1 Background", 1], ["2 Model", 0]]);
assert.strictEqual(nav[0].pageLabel, "p.1");
assert.strictEqual(nav[1].pageLabel, "p.1–2");
assert.deepStrictEqual(core.buildSectionTree([]), []);
const longTail = core.buildSectionTree([
  { level: 1, title: "A" }, { level: 3, title: "A.1.1" }, { level: 2, title: "A.2" },
]);
assert.deepStrictEqual(longTail.map((n) => n.section.title), ["A"]);
assert.deepStrictEqual(longTail[0].children.map((n) => n.section.title), ["A.1.1", "A.2"]);

// ---- 4) meta rows omit missing fields -------------------------------------
assert.deepStrictEqual(core.metaRows(payload.meta).map((row) => row.key),
  ["authors", "year", "venue", "doi", "source"]);
assert.deepStrictEqual(core.metaRows({ title: "only" }), []);
assert.strictEqual(core.pageRangeLabel(null, null), "");
assert.strictEqual(core.pageRangeLabel(3, 3), "p.3");

// ---- 5) metadata card markup ----------------------------------------------
const metaHtml = core.paperMetaHtml(payload, escapeHtml);
assert.ok(metaHtml.includes("Attention Is All You Need"), "title rendered");
assert.ok(metaHtml.includes("Ashish Vaswani · Noam Shazeer"), "authors joined");
assert.ok(metaHtml.includes("10.5555/3295222.3295349"), "doi rendered");
assert.ok(metaHtml.includes("Dominant") === false, "abstract case is not fabricated");
assert.ok(metaHtml.includes("transformer") && metaHtml.includes("paper-keyword"), "keywords");
assert.ok(!/undefined|null/.test(metaHtml), "no placeholder garbage");
// a document with nothing meta-worthy renders an empty card, not "undefined"
assert.strictEqual(core.paperMetaHtml({ doc_kind: "paper", sections: [] }, escapeHtml), "");
// escaping: hostile fixture values never become markup
const hostile = core.paperMetaHtml(
  { doc_kind: "paper", meta: { title: "<img src=x onerror=1>" }, sections: [{ title: "x" }] },
  escapeHtml,
);
assert.ok(!hostile.includes("<img src=x"), "title escaped");

// ---- 6) section nav + body markup -----------------------------------------
const navHtml = core.sectionNavHtml(payload, escapeHtml);
assert.ok(navHtml.includes('data-paper-section="0"'));
assert.ok(navHtml.includes('data-paper-section="2"'));
assert.ok(navHtml.includes("p.1–2"), "page range in nav");
const bodyHtml = core.sectionBodyHtml(payload, escapeHtml);
assert.ok(bodyHtml.includes('id="paper-section-0"'), "anchor ids");
assert.ok(bodyHtml.includes("<h2"), "level 1 -> h2");
assert.ok(bodyHtml.includes("<h3"), "level 2 -> h3");
assert.ok(core.sectionNavHtml({ sections: [] }, escapeHtml) === "");
assert.ok(core.sectionBodyHtml({ sections: [] }, escapeHtml) === "");

// ---- 7) references: resolved jump link, unresolved plain ------------------
const refHtml = core.referenceListHtml(payload, escapeHtml);
assert.ok(refHtml.includes('href="#doc/doc-ref-1"'), "resolved reference links into the library");
assert.ok(refHtml.includes("[1]") && refHtml.includes("[2]"), "indexed");
assert.strictEqual((refHtml.match(/paper-ref-link/g) || []).length, 1,
  "only the resolved reference gets a link");
assert.strictEqual(core.referenceHref({ resolved_document_id: "" }), "");
assert.strictEqual(core.referenceLabel({ raw: "[9] raw only" }), "[9] raw only");
// a failed/best-effort entry keeps its raw text *and* shows a status
assert.deepStrictEqual(view.references[1].notes, ["authors-unparsed"]);
assert.deepStrictEqual(view.references[0].notes, []);
assert.ok(refHtml.includes("paper-ref-status"), "parse status is rendered");
assert.ok(refHtml.includes("authors-unparsed"), "the status text is the evidence note");
assert.ok(refHtml.includes("[2] Anonymous preprint"), "raw text is kept for the failed entry");

// ---- 7b) import success vs metadata-extraction status are separate ---------
assert.strictEqual(core.paperMetaStatusLabel("ok"), "元数据已提取");
assert.ok(core.paperMetaStatusLabel("failed").includes("可重新提取"));
assert.ok(core.paperMetaStatusLabel("empty").includes("可重新提取"));
assert.strictEqual(core.paperMetaStatusLabel(""), "");

// ---- 8) active-section picker ---------------------------------------------
assert.strictEqual(core.activeSectionIndex([0, 500, 1200], 0), 0);
assert.strictEqual(core.activeSectionIndex([0, 500, 1200], 700), 1);
assert.strictEqual(core.activeSectionIndex([0, 500, 1200], 99999), 2);
assert.strictEqual(core.activeSectionIndex([], 10), -1);

// ---- 9) the API's 1-based page label wins over the raw 0-based indexes -----
const labelled = core.normalizeSection({
  level: 1, title: "S", page_start: 0, page_end: 0, page_label: "p.1",
});
assert.strictEqual(labelled.pageStart, 0, "raw P1 index is preserved");
assert.strictEqual(labelled.pageLabel, "p.1", "display label comes from the API");
const fallback = core.normalizeSection({ level: 1, title: "S", page_start: 3, page_end: 5 });
assert.strictEqual(fallback.pageLabel, "p.3–5", "fixtures without page_label fall back");
// the markup builders re-normalize their input, so normalization must be idempotent
const rebuilt = core.normalizeSection(labelled);
assert.strictEqual(rebuilt.pageLabel, "p.1", "page_label survives a second pass");
assert.strictEqual(rebuilt.pageStart, 0, "raw index survives a second pass");

// ---- 10) library_cards carries the same marker ----------------------------
assert.strictEqual(cards.isPaperDoc({ doc_kind: "paper" }), true);
assert.strictEqual(cards.isPaperDoc({ metadata: { doc_kind: "paper" } }), true);
assert.strictEqual(cards.isPaperDoc({ doc_kind: "manuscript" }), false);
assert.strictEqual(cards.isPaperDoc({}), false);
assert.strictEqual(cards.cardViewModel({ doc_kind: "paper" }).paper, true);
const paperCardHtml = cards.cardHtml({ document_id: "p", doc_kind: "paper", title: "T" }, escapeHtml);
assert.ok(paperCardHtml.includes("doc-paper-badge"), "paper badge in the grid card");
assert.ok(!cards.cardHtml({ document_id: "d", title: "T" }, escapeHtml).includes("doc-paper-badge"),
  "non-paper cards stay unmarked");

// ---- 11) router: #paper deeplink ------------------------------------------
globalThis.document = {
  querySelector: () => null,
  createElement: () => ({ textContent: "", innerHTML: "" }),
};
globalThis.location = { hash: "#library" };
const router = await load("js/router.js");
assert.deepStrictEqual(router.parseHash("#paper/p%201"), { name: "paper", id: "p 1" });
assert.deepStrictEqual(router.parseHash("#paper"), { name: "library" });
assert.strictEqual(router.parseHash("#doc/p1").name, "doc", "plain doc route unchanged");

console.log("paper_view: all assertions passed ✓");
