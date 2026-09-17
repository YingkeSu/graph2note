/* graph2note — paper reading view: pure view-model + markup builders (P3).

   No imports and no DOM access at load time, so the Node contract test
   (tests/paper_view.mjs) exercises the real normalization and markup without a
   browser.  The shape consumed here is SPEC §2: PaperMeta / PaperSection /
   PaperReference; every field is optional and missing data must degrade to
   "nothing rendered", never to placeholder garbage.

   The module never decides *where* data comes from — ``views/paper.js`` fetches
   the read-only ``/api/papers/*`` projection and hands the payload to these
   builders.
*/
"use strict";

export const PAPER_KIND = "paper";
export const MAX_NAV_TITLE = 80;

/* ---------- coercion (defensive: the payload may predate P1/P2) ---------- */

function text(value) {
  if (value == null) return "";
  return typeof value === "string" ? value.trim() : String(value).trim();
}

function textList(value) {
  if (!Array.isArray(value)) return [];
  return value.map(text).filter(Boolean);
}

function integerOrNull(value) {
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  if (typeof value === "string" && /^-?\d+$/.test(value.trim())) return Number(value.trim());
  return null;
}

function escapeFn(escape) {
  return typeof escape === "function" ? escape : (value) => text(value);
}

/* ---------- normalized shapes ---------- */

export function paperDocKind(payload) {
  if (!payload || typeof payload !== "object") return "";
  return text(payload.doc_kind);
}

export function normalizeMeta(meta) {
  const source = meta && typeof meta === "object" ? meta : {};
  return {
    title: text(source.title),
    authors: textList(source.authors),
    year: integerOrNull(source.year),
    venue: text(source.venue),
    doi: text(source.doi),
    abstract: typeof source.abstract === "string" ? source.abstract.trim() : "",
    keywords: textList(source.keywords),
    source: text(source.source),
  };
}

export function normalizeSection(section) {
  const source = section && typeof section === "object" ? section : {};
  let level = integerOrNull(source.level);
  if (level == null || level < 1) level = 1;
  // Accept both the API's snake_case and this module's own camelCase output so
  // the builders stay idempotent when handed an already-normalized section.
  const pageStart = integerOrNull(source.page_start != null ? source.page_start : source.pageStart);
  const pageEnd = integerOrNull(source.page_end != null ? source.page_end : source.pageEnd);
  return {
    level,
    title: text(source.title),
    text: typeof source.text === "string" ? source.text : "",
    pageStart,
    pageEnd,
    // The API already sends a 1-based display range (``page_label``); fall back
    // to the raw indexes only for hand-built fixtures.
    pageLabel: text(source.page_label) || text(source.pageLabel)
      || pageRangeLabel(pageStart, pageEnd),
  };
}

export function normalizeReference(reference) {
  const source = reference && typeof reference === "object" ? reference : {};
  return {
    raw: text(source.raw),
    title: text(source.title),
    authors: textList(source.authors),
    year: integerOrNull(source.year),
    doi: text(source.doi),
    resolvedDocumentId: text(
      source.resolved_document_id != null ? source.resolved_document_id : source.resolvedDocumentId,
    ),
    // Best-effort parse status from references_provenance (e.g.
    // "authors-unparsed"); the raw text above is always kept.
    notes: textList(source.notes),
  };
}

export function normalizePaperView(payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  return {
    documentId: text(source.document_id),
    docKind: paperDocKind(source),
    title: text(source.title),
    meta: normalizeMeta(source.meta),
    sections: (Array.isArray(source.sections) ? source.sections : []).map(normalizeSection),
    references: (Array.isArray(source.references) ? source.references : []).map(normalizeReference),
  };
}

/* A paper renders as the reading view only when it is a paper *and* the
   structural split produced at least one section; contract degradation for an
   old paper document without sections is the standard document view. */
export function isPaperView(payload) {
  if (paperDocKind(payload) !== PAPER_KIND) return false;
  return Array.isArray(payload.sections) && payload.sections.length > 0;
}

/* ---------- derived view data ---------- */

/** Human page range, e.g. ``p.3`` / ``p.3–5``; empty when unknown. */
export function pageRangeLabel(start, end) {
  if (start == null && end == null) return "";
  if (start != null && end != null && start !== end) return `p.${start}–${end}`;
  return `p.${start != null ? start : end}`;
}

/** Flat-level sections -> nested tree (the "PaperSection 树"). */
export function buildSectionTree(sections) {
  const nodes = [];
  const stack = [];
  (Array.isArray(sections) ? sections : []).forEach((raw, index) => {
    const section = normalizeSection(raw);
    const node = { index, section, children: [] };
    while (stack.length && stack[stack.length - 1].section.level >= section.level) stack.pop();
    if (stack.length) stack[stack.length - 1].children.push(node);
    else nodes.push(node);
    stack.push(node);
  });
  return nodes;
}

/** Flatten the tree into nav rows carrying a display depth (for <ol> nesting). */
export function sectionNavItems(sections) {
  const items = [];
  const walk = (nodes, depth) => {
    nodes.forEach((node) => {
      items.push({
        index: node.index,
        level: node.section.level,
        depth,
        title: node.section.title,
        pageLabel: node.section.pageLabel,
      });
      walk(node.children, depth + 1);
    });
  };
  walk(buildSectionTree(sections), 0);
  return items;
}

/** Ordered metadata rows; empty fields are omitted (no placeholder garbage). */
export function metaRows(meta) {
  const m = normalizeMeta(meta);
  const rows = [];
  if (m.authors.length) rows.push({ key: "authors", label: "作者", value: m.authors.join(" · ") });
  if (m.year != null) rows.push({ key: "year", label: "年份", value: String(m.year) });
  if (m.venue) rows.push({ key: "venue", label: "发表", value: m.venue });
  if (m.doi) rows.push({ key: "doi", label: "DOI", value: m.doi });
  if (m.source) rows.push({ key: "source", label: "来源", value: m.source });
  return rows;
}

/** Human label for the import job's metadata status.
 *
 * Import success and metadata extraction are independent outcomes (issue
 * PRR/02): the paper can import fine while extraction finds nothing or fails,
 * so the two are surfaced separately instead of collapsing into one message.
 */
export function paperMetaStatusLabel(status) {
  if (status === "ok") return "元数据已提取";
  if (status === "failed") return "元数据提取失败（可重新提取）";
  if (status === "empty") return "未提取到元数据（可重新提取）";
  return "";
}

/** Prefer the parsed title, fall back to the raw citation text. */
export function referenceLabel(reference) {
  const ref = normalizeReference(reference);
  return ref.title || ref.raw || ref.doi || "";
}

/** In-library jump target; empty when the reference is not resolved. */
export function referenceHref(reference) {
  const id = normalizeReference(reference).resolvedDocumentId;
  return id ? `#doc/${encodeURIComponent(id)}` : "";
}

/** Index of the section whose top is closest above ``scrollTop``. */
export function activeSectionIndex(offsets, scrollTop, margin = 8) {
  if (!Array.isArray(offsets) || !offsets.length) return -1;
  let active = 0;
  for (let i = 0; i < offsets.length; i += 1) {
    if (offsets[i] - margin <= scrollTop) active = i;
    else break;
  }
  return active;
}

/* ---------- markup builders (pure strings; escaped by the caller's fn) ----- */

export function paperMetaHtml(payload, escape) {
  const esc = escapeFn(escape);
  const view = normalizePaperView(payload);
  const title = view.meta.title || view.title;
  if (!title && !metaRows(view.meta).length && !view.meta.keywords.length && !view.meta.abstract) {
    return "";
  }
  const rows = metaRows(view.meta).map((row) =>
    `<div class="paper-meta-row"><span class="paper-meta-label">${esc(row.label)}</span><span class="paper-meta-value">${esc(row.value)}</span></div>`
  ).join("");
  const keywords = view.meta.keywords.length
    ? `<div class="paper-keywords">${view.meta.keywords.map((keyword) =>
      `<span class="paper-keyword">${esc(keyword)}</span>`).join("")}</div>`
    : "";
  const abstract = view.meta.abstract
    ? `<p class="paper-abstract">${esc(view.meta.abstract)}</p>`
    : "";
  const heading = title ? `<h1 class="paper-title">${esc(title)}</h1>` : "";
  const grid = rows ? `<div class="paper-meta-grid">${rows}</div>` : "";
  return `${heading}${grid}${keywords}${abstract}`;
}

export function sectionNavHtml(payload, escape) {
  const esc = escapeFn(escape);
  const view = normalizePaperView(payload);
  const items = sectionNavItems(view.sections);
  if (!items.length) return "";
  return `<ol class="paper-nav-list">${items.map((item) => {
    const page = item.pageLabel
      ? `<span class="paper-nav-page dim">${esc(item.pageLabel)}</span>` : "";
    return `<li class="paper-nav-item level-${item.level}">
      <button type="button" class="paper-nav-link" data-paper-section="${item.index}"
              title="${esc(item.title || "无标题章节")}">${esc(item.title || "无标题章节")}${page}</button></li>`;
  }).join("")}</ol>`;
}

export function sectionBodyHtml(payload, escape) {
  const esc = escapeFn(escape);
  const view = normalizePaperView(payload);
  return view.sections.map((section, index) => {
    const tag = section.level <= 1 ? "h2" : section.level === 2 ? "h3" : "h4";
    const page = section.pageLabel
      ? `<span class="paper-section-page dim">${esc(section.pageLabel)}</span>` : "";
    return `<section class="paper-section" id="paper-section-${index}"
        data-section-index="${index}" tabindex="-1">
      <${tag} class="paper-section-title">${esc(section.title || "无标题章节")}${page}</${tag}>
      <div class="paper-section-text">${esc(section.text)}</div>
    </section>`;
  }).join("");
}

export function referenceListHtml(payload, escape) {
  const esc = escapeFn(escape);
  const view = normalizePaperView(payload);
  return view.references.map((reference, index) => {
    const href = referenceHref(reference);
    const label = referenceLabel(reference);
    const link = href
      ? ` <a class="paper-ref-link" href="${esc(href)}" title="打开库内关联论文">库内文档 ↗</a>`
      : "";
    const meta = [reference.authors.join(" · "),
      reference.year != null ? String(reference.year) : "",
      reference.doi].filter(Boolean).join(" · ");
    const metaLine = meta ? `<span class="paper-ref-meta dim">${esc(meta)}</span>` : "";
    const rawLine = reference.raw && reference.raw !== label
      ? `<span class="paper-ref-raw dim">${esc(reference.raw)}</span>` : "";
    const statusLine = reference.notes.length
      ? `<span class="paper-ref-status dim">${esc(reference.notes.join(" · "))}</span>` : "";
    return `<li class="paper-reference" id="paper-reference-${index}">
      <span class="paper-ref-index">[${index + 1}]</span>
      <span class="paper-ref-body">
        <span class="paper-ref-title">${esc(label)}</span>${metaLine}${rawLine}${statusLine}
      </span>${link}</li>`;
  }).join("");
}

