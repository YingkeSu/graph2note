/* graph2note — paper reading view (P3, SPEC §2).

   A ``doc_kind == "paper"`` document opens into a dedicated reading surface:
   a metadata card, a section navigation tree, the section body and the
   bibliography (entries already resolved to an in-library document link back
   into the library).  All data comes from the read-only ``/api/papers/*``
   projection; this module owns no mutation.

   Routing: ``#paper/<id>`` is the explicit deep link.  ``#doc/<id>`` — the
   route the Library grid and the unified search panel already use — is
   re-registered here so a paper renders its reading view in place.  Every other
   document delegates to the untouched ``document.js`` view (paper.js is
   imported after document.js in app.js, so this registration wins).  A paper
   without sections degrades to the standard document view.

   Pure view-model + markup live in ``../paper_view_core.js`` and are covered by
   tests/paper_view.mjs.
*/
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { go, registerView } from "../router.js";
import { esc } from "../utils.js";
import { renderDocumentRoute } from "./document.js";
import {
  activeSectionIndex,
  isPaperView,
  normalizePaperView,
  paperMetaHtml,
  referenceListHtml,
  sectionBodyHtml,
  sectionNavHtml,
} from "../paper_view_core.js";

const DEFAULT_TITLE = "graph2note — 手稿电子化";

/* ---------- rendering ---------- */

function resetPaperView() {
  if (el.paperMeta) el.paperMeta.innerHTML = "";
  if (el.paperSectionNav) el.paperSectionNav.innerHTML = "";
  if (el.paperBody) el.paperBody.innerHTML = "";
  if (el.paperReferences) el.paperReferences.innerHTML = "";
  if (el.paperReferencesZone) el.paperReferencesZone.classList.add("hidden");
  if (el.paperStatus) el.paperStatus.textContent = "";
  document.title = DEFAULT_TITLE;
}

let activeObserver = null;

function teardownHighlight() {
  if (activeObserver && typeof activeObserver.disconnect === "function") {
    activeObserver.disconnect();
  }
  activeObserver = null;
}

function setActiveNav(index) {
  if (!el.paperSectionNav) return;
  el.paperSectionNav.querySelectorAll(".paper-nav-link").forEach((button) => {
    const active = Number(button.dataset.paperSection) === index;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  });
}

/* Highlight the section currently at the top of the reading pane.  Falls back
   to click-driven updates when IntersectionObserver is unavailable. */
function setupActiveHighlight() {
  teardownHighlight();
  setActiveNav(0);
  const sections = Array.from(document.querySelectorAll("#paper-body .paper-section"));
  if (!sections.length || typeof IntersectionObserver !== "function") return;
  const ratios = new Map();
  activeObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      ratios.set(entry.target, entry.isIntersecting ? entry.intersectionRatio : -1);
    });
    let best = 0;
    let bestRatio = -1;
    sections.forEach((node, index) => {
      const ratio = ratios.get(node) == null ? -1 : ratios.get(node);
      if (ratio > bestRatio) { bestRatio = ratio; best = index; }
    });
    setActiveNav(best);
  }, { root: null, rootMargin: "-72px 0px -55% 0px", threshold: [0, 0.25, 0.5, 1] });
  sections.forEach((node) => activeObserver.observe(node));
}

function wireSectionNav() {
  if (!el.paperSectionNav) return;
  el.paperSectionNav.querySelectorAll("[data-paper-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.paperSection);
      const target = document.getElementById(`paper-section-${index}`);
      if (target) {
        if (typeof target.scrollIntoView === "function") {
          target.scrollIntoView({ block: "start", behavior: "smooth" });
        }
        if (typeof target.focus === "function") {
          try { target.focus({ preventScroll: true }); } catch (_) { /* ignore */ }
        }
      }
      setActiveNav(index);
    });
  });
}

function setPaperError(message) {
  if (!el.paperStatus) return;
  el.paperStatus.textContent = "";
  const panel = document.createElement("p");
  panel.className = "paper-error";
  panel.setAttribute("role", "alert");
  panel.textContent = message;
  el.paperStatus.appendChild(panel);
}

function setPaperStatus(message) {
  if (!el.paperStatus) return;
  el.paperStatus.textContent = message || "";
}

/* Explicit historical back-fill: re-run the metadata/reference extractor over
   the already-imported paper text.  Manual fields are preserved server-side
   and a failed pass is retryable (nothing destructive happens). */
async function reextractPaperMetadata() {
  const id = state.docId;
  if (!id || state.busy) return;
  state.busy = true;
  setPaperStatus("正在重新提取元数据…");
  try {
    const result = await api(
      `/api/papers/${encodeURIComponent(id)}/metadata/extract`, { method: "POST" });
    const view = await api(`/api/papers/${encodeURIComponent(id)}/view`);
    renderPaperView(view);
    const extraction = result.extraction || {};
    const preserved = (extraction.preserved || []).length;
    if (extraction.status === "failed") {
      setPaperStatus(`元数据提取失败：${extraction.error || "未知错误"}（可重试）`);
    } else if (preserved) {
      setPaperStatus(`元数据已更新，保留了 ${preserved} 个手工字段。`);
    } else {
      setPaperStatus("元数据已更新。");
    }
  } catch (e) {
    setPaperStatus(`元数据提取失败：${e.message}（可重试）`);
  } finally {
    state.busy = false;
  }
}

export function renderPaperView(payload) {
  const view = normalizePaperView(payload);
  if (!el.paperZone) return;
  document.querySelectorAll(".paper-section").forEach((node) => node.classList.remove("active"));
  el.paperZone.classList.remove("hidden");
  if (el.paperStatus) el.paperStatus.textContent = "";
  if (el.paperMeta) el.paperMeta.innerHTML = paperMetaHtml(view, esc);
  if (el.paperSectionNav) el.paperSectionNav.innerHTML = sectionNavHtml(view, esc);
  if (el.paperBody) el.paperBody.innerHTML = sectionBodyHtml(view, esc);
  if (el.paperReferencesZone && el.paperReferences) {
    el.paperReferencesZone.classList.toggle("hidden", view.references.length === 0);
    el.paperReferences.innerHTML = referenceListHtml(view, esc);
  }
  wireSectionNav();
  setupActiveHighlight();
  const metaEmpty = !view.meta.title && !view.meta.authors.length
    && !view.meta.abstract;
  if (metaEmpty) {
    setPaperStatus("未提取到元数据，可点击「重新提取元数据」重试。");
  }
  const heading = view.meta.title || view.title;
  document.title = heading ? `${heading} — graph2note` : DEFAULT_TITLE;
}

/* ---------- routing ---------- */

/* ``#paper/<id>`` and ``#doc/<id>`` share one handler: fetch the read-only
   projection, render the paper view when the contract says it is a paper,
   otherwise fall back to the pre-existing document workspace unchanged. */
export async function renderPaperRoute(route) {
  const id = route && route.id;
  if (!id) { go("#library"); return; }
  state.docId = id;
  teardownHighlight();
  let payload = null;
  try {
    payload = await api(`/api/papers/${encodeURIComponent(id)}/view`);
  } catch (_) {
    payload = null;
  }
  if (!isPaperView(payload)) {
    resetPaperView();
    if (route.name === "paper") { go(`#doc/${encodeURIComponent(id)}`); return; }
    return renderDocumentRoute(route);
  }
  try {
    renderPaperView(payload);
  } catch (e) {
    resetPaperView();
    if (route.name === "paper") { go(`#doc/${encodeURIComponent(id)}`); return; }
    return renderDocumentRoute(route);
  }
}

registerView("paper", renderPaperRoute);
/* Re-register ``doc`` so a paper document renders its reading view from the
   Library grid and the unified search panel without those call sites changing.
   Non-paper documents delegate to document.js's exported handler verbatim. */
registerView("doc", renderPaperRoute);

if (el.paperBack) {
  el.paperBack.addEventListener("click", () => go("#library"));
}

if (el.paperReextract) {
  el.paperReextract.addEventListener("click", reextractPaperMetadata);
}

/* P1 puts ``doc_kind`` on the ``/api/documents`` summary, so the Library grid
   badge is rendered directly by ``library_cards`` — no extra index fetch. */
