/* graph2note — unified search panel (P3).
 *
 * One entry point for "search document titles + document Markdown + parsed PDF
 * pages", reachable from the topbar search box or ⌘K.  Results are grouped into
 * documents and PDF pages; a document opens the editor, a PDF result opens the
 * original page.  "就这些结果提问" hands the query to the Q&A view.
 *
 * This module is deliberately self-contained: it talks only to `/api/search`
 * and to well-known element ids, so it runs unchanged on the legacy shell and
 * on the U1 module shell (which provides `#global-search-input` already).
 * Pure helpers are exported so they can be unit-tested under Node without a DOM.
 */
"use strict";

export const PENDING_ASK_KEY = "graph2note.pendingAsk";
const DEBOUNCE_MS = 180;

/* ---------- pure helpers (Node-testable) ---------- */

export function groupSearchResults(payload) {
  const groups = (payload && payload.groups) || {};
  const documents = groups.documents || (payload && payload.documents) || [];
  const pdfPages = groups.pdf_pages || (payload && payload.pdf_pages) || [];
  return { documents: documents.slice(), pdfPages: pdfPages.slice() };
}

export function displayPage(hit) {
  if (hit && hit.page_number != null) return hit.page_number;
  return (hit && hit.page_index != null ? hit.page_index : 0) + 1;
}

export function writePendingAsk(storage, query) {
  const q = (query || "").trim();
  if (!q) return "";
  try { storage.setItem(PENDING_ASK_KEY, q); } catch (_) { /* ignore */ }
  return q;
}

export function readPendingAsk(storage) {
  try { return (storage.getItem(PENDING_ASK_KEY) || "").trim(); } catch (_) { return ""; }
}

export function clearPendingAsk(storage) {
  try { storage.removeItem(PENDING_ASK_KEY); } catch (_) { /* ignore */ }
}

/* The Q&A view lives on P2's first-class `#ask` view, on U1's temporary
 * `#pdf-search` shell and on the legacy Library screen; detect which shell we
 * are on so the prefill lands on the view that hosts `#pdf-qa-input`.  P2 kept
 * `#pdf-search` as an alias route but renamed the zone element to `#ask-zone`,
 * so the container id — not the route — is what tells the shells apart. */
export function qaRoute(doc) {
  if (doc.getElementById("ask-zone")) return "#ask";
  return doc.getElementById("pdf-search-zone") ? "#pdf-search" : "#library";
}

/* ---------- panel wiring ---------- */

function isEditable(node) {
  if (!node) return false;
  const tag = (node.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || node.isContentEditable;
}

function el(doc, id) { return doc.getElementById(id); }

export function initSearchPanel(env = {}) {
  const doc = env.document || (typeof document !== "undefined" ? document : null);
  const win = env.window || (typeof window !== "undefined" ? window : null);
  if (!doc || !win) return null;

  const panel = el(doc, "global-search-panel");
  if (!panel) return null;
  const storage = env.storage || (() => {
    try { return win.sessionStorage; } catch (_) { return null; }
  })();
  const fetchImpl = env.fetch || (typeof win.fetch === "function" ? win.fetch.bind(win) : null);

  const topbarInput = el(doc, "global-search-input");
  const panelInput = el(doc, "global-search-panel-input");
  const status = el(doc, "global-search-status");
  const results = el(doc, "global-search-results");
  const documentsBody = el(doc, "global-search-documents");
  const pdfBody = el(doc, "global-search-pdf-pages");
  const documentsCount = el(doc, "global-search-documents-count");
  const pdfCount = el(doc, "global-search-pdf-count");
  const closeButton = el(doc, "global-search-close");
  const askButton = el(doc, "global-search-ask");

  let query = "";
  let timer = null;
  let requestId = 0;

  function open(initial) {
    panel.classList.remove("hidden");
    if (initial != null) {
      query = String(initial);
      if (panelInput) panelInput.value = query;
      if (topbarInput) topbarInput.value = query;
    }
    if (panelInput) panelInput.focus();
    if (query.trim()) queueSearch(0);
  }

  function close() {
    panel.classList.add("hidden");
    // do not leave focus trapped in the hidden field: ⌘K must work again
    if (panelInput && doc.activeElement === panelInput) {
      try { panelInput.blur(); } catch (_) { /* ignore */ }
    }
  }

  function queueSearch(delay = DEBOUNCE_MS) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(runSearch, delay);
  }

  function setStatus(text) {
    if (status) status.textContent = text;
  }

  function snippetNode(snippet, terms) {
    const span = doc.createElement("div");
    span.className = "search-hit-snippet";
    const text = snippet || "";
    if (!terms.length) { span.textContent = text; return span; }
    const lowered = text.toLowerCase();
    let cursor = 0;
    const marks = [];
    for (const term of terms) {
      const t = term.toLowerCase();
      if (!t) continue;
      let from = 0;
      while (from < lowered.length) {
        const at = lowered.indexOf(t, from);
        if (at === -1) break;
        marks.push([at, at + t.length]);
        from = at + t.length;
      }
    }
    marks.sort((a, b) => a[0] - b[0]);
    for (const [start, end] of marks) {
      if (start < cursor) continue;
      span.appendChild(doc.createTextNode(text.slice(cursor, start)));
      const mark = doc.createElement("mark");
      mark.textContent = text.slice(start, end);
      span.appendChild(mark);
      cursor = end;
    }
    span.appendChild(doc.createTextNode(text.slice(cursor)));
    return span;
  }

  function documentCard(hit, terms) {
    const card = doc.createElement("div");
    card.className = "search-hit search-hit-doc";
    card.dataset.kind = "document";
    card.dataset.documentId = hit.document_id || "";
    const head = doc.createElement("div");
    head.className = "search-hit-head";
    const link = doc.createElement("a");
    link.className = "search-hit-title";
    link.href = "#doc/" + encodeURIComponent(hit.document_id || "");
    link.textContent = hit.title || hit.document_id || "";
    head.appendChild(link);
    if (hit.matched_blocks > 1) {
      const badge = doc.createElement("span");
      badge.className = "search-hit-page dim";
      badge.textContent = `${hit.matched_blocks} 处匹配`;
      head.appendChild(badge);
    }
    card.appendChild(head);
    card.appendChild(snippetNode(hit.snippet, terms));
    card.addEventListener("click", (event) => {
      if (event.target && event.target.tagName === "A") return; // let the link work
      win.location.hash = "#doc/" + encodeURIComponent(hit.document_id || "");
    });
    return card;
  }

  function pdfCard(hit, terms) {
    const card = doc.createElement("div");
    card.className = "search-hit search-hit-pdf";
    card.dataset.kind = "pdf_page";
    card.dataset.documentId = hit.document_id || "";
    card.dataset.pdfId = hit.pdf_id || "";
    const head = doc.createElement("div");
    head.className = "search-hit-head";
    const link = doc.createElement("a");
    link.className = "search-hit-title search-pdf-page";
    link.href = hit.source_page_url || hit.pdf_page_url || "#";
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = (hit.pdf_name ? hit.pdf_name + " · " : "")
      + (hit.title || hit.document_id || "");
    head.appendChild(link);
    const page = doc.createElement("span");
    page.className = "search-hit-page dim";
    page.textContent = `第 ${displayPage(hit)} 页`;
    head.appendChild(page);
    card.appendChild(head);
    card.appendChild(snippetNode(hit.snippet, terms));
    const links = doc.createElement("div");
    links.className = "search-hit-links";
    const editor = doc.createElement("a");
    editor.href = "#doc/" + encodeURIComponent(hit.document_id || "");
    editor.textContent = "打开校对文档";
    links.appendChild(editor);
    const original = doc.createElement("a");
    original.href = hit.source_page_url || hit.pdf_page_url || "#";
    original.target = "_blank";
    original.rel = "noopener";
    original.textContent = "查看原 PDF 页";
    links.appendChild(original);
    card.appendChild(links);
    card.addEventListener("click", (event) => {
      if (event.target && event.target.tagName === "A") return;
      win.open(original.href, "_blank", "noopener");
    });
    return card;
  }

  function render(payload) {
    const { documents, pdfPages } = groupSearchResults(payload);
    const terms = (payload && payload.tokens) || [];
    if (documentsBody) {
      documentsBody.innerHTML = "";
      for (const hit of documents) documentsBody.appendChild(documentCard(hit, terms));
    }
    if (pdfBody) {
      pdfBody.innerHTML = "";
      for (const hit of pdfPages) pdfBody.appendChild(pdfCard(hit, terms));
    }
    if (documentsCount) documentsCount.textContent = documents.length ? `${documents.length}` : "";
    if (pdfCount) pdfCount.textContent = pdfPages.length ? `${pdfPages.length}` : "";
  }

  async function runSearch() {
    const q = (query || "").trim();
    const id = ++requestId;
    if (!q) {
      render({ documents: [], pdf_pages: [] });
      setStatus("");
      return;
    }
    setStatus("检索中…");
    let payload;
    try {
      if (!fetchImpl) throw new Error("fetch unavailable");
      const res = await fetchImpl(`/api/search?q=${encodeURIComponent(q)}`);
      payload = await res.json();
    } catch (err) {
      if (id !== requestId) return;
      setStatus("搜索失败：" + (err && err.message ? err.message : err));
      return;
    }
    if (id !== requestId) return; // a newer query already superseded this one
    render(payload);
    setStatus(payload.total
      ? `命中 ${payload.total} 条（文档 ${(payload.documents || []).length} · PDF 页 ${(payload.pdf_pages || []).length}）`
      : (payload.message || "没有匹配的内容。"));
  }

  /* ---------- cross-view hand-off: "就这些结果提问" ---------- */

  function applyPendingAsk() {
    const pending = readPendingAsk(storage);
    if (!pending) return;
    const input = el(doc, "pdf-qa-input");
    if (!input) return;
    input.value = pending;
    clearPendingAsk(storage);
    try { input.focus(); } catch (_) { /* ignore */ }
    if (typeof input.scrollIntoView === "function") input.scrollIntoView({ block: "center" });
  }

  function askAboutResults() {
    const q = (query || "").trim();
    if (!q) { setStatus("先输入检索词。"); return; }
    writePendingAsk(storage, q);
    close();
    const route = qaRoute(doc);
    if (win.location.hash === route) applyPendingAsk();
    else win.location.hash = route;
  }

  /* ---------- events ---------- */

  if (topbarInput) {
    topbarInput.addEventListener("focus", () => open(topbarInput.value || ""));
    topbarInput.addEventListener("input", () => {
      query = topbarInput.value || "";
      if (panelInput) panelInput.value = query;
      open(query);
    });
    const form = topbarInput.form || el(doc, "global-search-form");
    if (form) form.addEventListener("submit", (event) => {
      event.preventDefault();
      query = topbarInput.value || "";
      open(query);
    });
  }
  if (panelInput) {
    panelInput.addEventListener("input", () => {
      query = panelInput.value || "";
      if (topbarInput) topbarInput.value = query;
      queueSearch();
    });
  }
  if (closeButton) closeButton.addEventListener("click", close);
  if (askButton) askButton.addEventListener("click", askAboutResults);
  panel.addEventListener("click", (event) => { if (event.target === panel) close(); });

  doc.addEventListener("keydown", (event) => {
    const key = (event.key || "").toLowerCase();
    if ((event.metaKey || event.ctrlKey) && key === "k") {
      if (isEditable(event.target)) return; // never steal the shortcut from a field
      event.preventDefault();
      open(topbarInput ? topbarInput.value : "");
      return;
    }
    if (key === "escape" && !panel.classList.contains("hidden")) {
      event.preventDefault();
      close();
    }
  });

  win.addEventListener("hashchange", () => { setTimeout(applyPendingAsk, 0); });
  applyPendingAsk();

  const api = { open, close, applyPendingAsk, askAboutResults, getQuery: () => query };
  if (win.__g2nSearchPanel === undefined) win.__g2nSearchPanel = api;
  return api;
}

/* Auto-init in the browser; importing under Node (tests) stays side-effect free. */
if (typeof document !== "undefined" && typeof window !== "undefined") {
  const boot = () => { try { initSearchPanel(); } catch (_) { /* never block the app */ } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
