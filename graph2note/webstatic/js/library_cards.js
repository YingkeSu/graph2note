/* graph2note — Library card view-model, lazy thumbnail loader and card action
   wiring (U2).

   Pure module: no imports and no DOM access at load time, so the Node contract
   test (tests/library_cards.mjs) exercises the real card markup, lazy-loading
   gate and click/quick-action dispatch without a browser.

   Date contract: the card never re-derives the four-timestamp priority chain.
   ``/api/documents`` already returns ``effective_time`` selected by the
   existing pure function ``graph2note.metadata.select_effective_time``
   (document_time > capture_time > import_time); this module only formats it.
*/
"use strict";

export const MAX_TAG_CHIPS = 3;
export const DENSITIES = ["comfortable", "compact"];
export const DEFAULT_DENSITY = "compact";
export const DENSITY_KEY = "graph2note.library-density";

export function normalizeDensity(value) {
  return DENSITIES.includes(value) ? value : DEFAULT_DENSITY;
}

/** Readable card title: Markdown headline first, filename as the fallback. */
export function cardTitle(doc) {
  const headline = String((doc && doc.headline) || "").trim();
  if (headline) return headline;
  const title = String((doc && (doc.title || doc.document_id)) || "").trim();
  return title || "未命名文档";
}

/** Filename shown as secondary info only when the headline differs from it. */
export function cardFilename(doc) {
  const title = String((doc && doc.title) || "").trim();
  const headline = String((doc && doc.headline) || "").trim();
  return title && title !== headline ? title : "";
}

/** Day-precision date from the API's effective-time selection (never recomputed). */
export function cardDate(doc) {
  const value = doc && doc.effective_time && doc.effective_time.value;
  const day = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : "";
}

/** Which slot of the priority chain produced the date (tooltip provenance). */
export function cardDateSource(doc) {
  const slot = doc && doc.effective_time;
  return slot && slot.source ? String(slot.source) : "";
}

export function cardTags(doc, max = MAX_TAG_CHIPS) {
  const tags = Array.isArray(doc && doc.tags) ? doc.tags.filter(Boolean).map(String) : [];
  return {
    visible: tags.slice(0, max),
    overflow: Math.max(0, tags.length - max),
    total: tags.length,
  };
}

/** P3: a paper document carries ``doc_kind == "paper"`` (SPEC §2).  The kind
    may arrive on the summary directly or nested under ``metadata`` while P1's
    storage landing point settles, so both are accepted. */
export function isPaperDoc(doc) {
  if (!doc || typeof doc !== "object") return false;
  const direct = String(doc.doc_kind || "").trim();
  if (direct) return direct === "paper";
  const metadata = doc.metadata && typeof doc.metadata === "object" ? doc.metadata : {};
  return String(metadata.doc_kind || "").trim() === "paper";
}

export function cardSource(doc) {
  const kind = (doc && doc.source_kind) || ((doc && doc.source_pdf) ? "pdf" : "image");
  if (kind === "pdf") {
    return { kind: "pdf", icon: "PDF", label: (doc && doc.source_label) || "PDF 页" };
  }
  return { kind: "image", icon: "图片", label: (doc && doc.source_label) || "图片上传" };
}

export function cardViewModel(doc) {
  const { visible, overflow, total } = cardTags(doc);
  return {
    id: String((doc && doc.document_id) || ""),
    title: cardTitle(doc),
    filename: cardFilename(doc),
    date: cardDate(doc),
    dateSource: cardDateSource(doc),
    tags: visible,
    tagOverflow: overflow,
    tagTotal: total,
    source: cardSource(doc),
    paper: isPaperDoc(doc),
    thumbnail: (doc && doc.thumbnail_url) || "",
  };
}

/** Card markup.  Thumbnails carry ``data-src`` only, so parsing the grid never
    issues an image request; ``createThumbnailLoader`` assigns ``src`` when the
    card enters the viewport. */
export function cardHtml(doc, escape) {
  const vm = cardViewModel(doc);
  const esc = typeof escape === "function" ? escape : (value) => String(value == null ? "" : value);
  const thumb = vm.thumbnail
    ? `<img class="doc-thumb" loading="lazy" decoding="async" alt="" data-src="${esc(vm.thumbnail)}" /><span class="doc-thumb-placeholder">预览暂不可用</span>`
    : `<div class="doc-thumb doc-thumb-missing"><span>暂无预览</span></div>`;
  const chips = vm.tags.map((tag) => `<span class="doc-chip">#${esc(tag)}</span>`).join("");
  const overflow = vm.tagOverflow
    ? `<span class="doc-chip doc-chip-overflow" title="${esc(vm.tagTotal)} 个标签">+${vm.tagOverflow}</span>`
    : "";
  const date = vm.date
    ? `<time class="doc-date" datetime="${esc(vm.date)}" title="${esc(vm.dateSource ? "有效时间来源：" + vm.dateSource : "")}">${esc(vm.date)}</time>`
    : `<span class="doc-date dim">无日期</span>`;
  const subtitle = vm.filename
    ? `<div class="doc-subtitle dim" title="${esc(vm.filename)}">${esc(vm.filename)}</div>`
    : "";
  // P3: paper documents get an explicit, non-colour-only marker in the grid.
  const paperBadge = vm.paper
    ? `<span class="doc-paper-badge" title="论文文档">论文</span>` : "";
  return `<article class="doc-card" data-id="${esc(vm.id)}" tabindex="0" role="button" aria-label="打开 ${esc(vm.title)}">
      <div class="thumb">
        ${thumb}
        <span class="doc-source" data-source-kind="${esc(vm.source.kind)}" title="${esc(vm.source.label)}" aria-label="${esc(vm.source.label)}">${vm.source.icon}</span>
        <div class="doc-card-actions">
          <button type="button" class="doc-action" data-card-action="reparse" title="重新解析" aria-label="重新解析">↻</button>
          <button type="button" class="doc-action danger" data-card-action="delete" title="删除" aria-label="删除">✕</button>
        </div>
      </div>
      <div class="doc-meta">
        <div class="doc-title" title="${esc(vm.title)}">${esc(vm.title)}</div>
        ${paperBadge}
        ${subtitle}
        <div class="doc-tags">${chips}${overflow}</div>
        <div class="doc-footer">${date}</div>
      </div>
    </article>`;
}

/** Viewport-gated thumbnail loader.

    ``makeObserver`` receives the IntersectionObserver callback and returns an
    observer with ``observe`` / ``unobserve`` / ``disconnect``.  Only images the
    browser reports as intersecting get their ``src`` assigned, so the initial
    request count tracks the visible cards instead of the whole library.  When
    IntersectionObserver is unavailable the loader degrades to assigning every
    ``src`` immediately. */
export function createThumbnailLoader({ makeObserver, load } = {}) {
  const assign = typeof load === "function" ? load : (img) => {
    const src = img.getAttribute("data-src");
    if (src) img.setAttribute("src", src);
    img.removeAttribute("data-src");
  };
  if (typeof makeObserver !== "function") {
    return {
      observe(img) { if (img) assign(img); },
      disconnect() {},
    };
  }
  const observer = makeObserver((entries, obs) => {
    for (const entry of entries) {
      if (!entry || !entry.isIntersecting) continue;
      if (obs && obs.unobserve) obs.unobserve(entry.target);
      assign(entry.target);
    }
  });
  return {
    observe(img) { if (img && observer && observer.observe) observer.observe(img); },
    disconnect() { if (observer && observer.disconnect) observer.disconnect(); },
  };
}

/** Wire card navigation + hover quick actions.

    Delete always asks for confirmation before calling ``handlers.remove``;
    reparse uses the same confirm idiom as the document view.  Kept to two
    selector shapes so the Node contract test can drive it with a tiny fake DOM. */
export function wireCardActions(root, handlers) {
  const cards = root && root.querySelectorAll ? root.querySelectorAll(".doc-card") : [];
  cards.forEach((card) => {
    const id = card.dataset ? card.dataset.id : "";
    if (card.addEventListener) {
      card.addEventListener("click", () => handlers.open(id));
      card.addEventListener("keydown", (event) => {
        if (event && (event.key === "Enter" || event.key === " ")) {
          if (event.preventDefault) event.preventDefault();
          handlers.open(id);
        }
      });
    }
    const buttons = card.querySelectorAll ? card.querySelectorAll("[data-card-action]") : [];
    buttons.forEach((button) => {
      if (!button.addEventListener) return;
      button.addEventListener("click", (event) => {
        if (event && event.stopPropagation) event.stopPropagation();
        const action = button.dataset ? button.dataset.cardAction : "";
        if (action === "delete") {
          if (handlers.confirmDelete && !handlers.confirmDelete(id)) return;
          handlers.remove(id);
        } else if (action === "reparse") {
          if (handlers.confirmReparse && !handlers.confirmReparse(id)) return;
          handlers.reparse(id);
        }
      });
    });
  });
}
