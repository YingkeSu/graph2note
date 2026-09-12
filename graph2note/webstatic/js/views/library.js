/* graph2note — Library view (document grid).

   U1: only the head + grid + empty state live here; collection tree -> sidebar,
   tag vocabulary -> #tags, PDF search/Q&A -> #pdf-search.
   U2: the grid renders identifiable knowledge cards (thumbnail / headline /
   effective date / tag chips / source icon), keeps thumbnails viewport-lazy and
   exposes density + hover quick actions. */
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { go, registerView, libraryHash } from "../router.js";
import { showToast, refreshCollectionTree } from "../ui.js";
import {
  DEFAULT_DENSITY,
  DENSITY_KEY,
  cardHtml,
  createThumbnailLoader,
  normalizeDensity,
  wireCardActions,
} from "../library_cards.js";
import {
  normalizeSuggestions,
  suggestionApplyBody,
  suggestionChipHtml,
  suggestionDocMap,
  suggestionsHtml,
  wireSuggestionActions,
  wireSuggestionChips,
} from "../collection_suggestions.js";

const SKELETON_COUNT = 8;
const DELETE_CONFIRM = "删除文档将移除原图、识别结果、Markdown 与全部附件，且不可恢复。确定删除？";
const REPARSE_CONFIRM = "重新解析将用新的识别结果覆盖当前 Markdown（您的编辑将被替换，旧内容仍在历史版本可查）。确定继续吗？";

let thumbnailLoader = null;
let suggestionPayload = null;

function readDensity() {
  try { return normalizeDensity(localStorage.getItem(DENSITY_KEY)); }
  catch (_) { return DEFAULT_DENSITY; }
}

function applyDensity(value) {
  const density = normalizeDensity(value || readDensity());
  state.libraryDensity = density;
  if (el.libraryGrid) el.libraryGrid.dataset.density = density;
  if (el.libraryDensity) {
    el.libraryDensity.querySelectorAll("button[data-density]").forEach((button) => {
      const active = button.dataset.density === density;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }
  try { localStorage.setItem(DENSITY_KEY, density); } catch (_) { /* ignore */ }
  return density;
}

/* ---------- collection suggestions (auto-organization issue 02) ---------- */

async function loadSuggestions() {
  try { suggestionPayload = await api("/api/collections/suggestions"); }
  catch (_) { suggestionPayload = null; }
  return suggestionPayload;
}

function pendingDocIds(topic) {
  const view = normalizeSuggestions(suggestionPayload);
  const group = view.groups.find((item) => item.topic === topic);
  if (!group) return [];
  return group.documents
    .filter((doc) => doc.status === "pending" || doc.status === "confirmation_required")
    .map((doc) => doc.documentId);
}

function renderSuggestionSection() {
  if (!el.collectionSuggestions) return;
  el.collectionSuggestions.innerHTML = suggestionsHtml(suggestionPayload, esc);
  wireSuggestionActions(el.collectionSuggestions, {
    generate: () => generateSuggestions(),
    accept: (data) => applySuggestion([data.documentId], []),
    reject: (data) => applySuggestion([], [data.documentId]),
    acceptGroup: (data) => applySuggestion(pendingDocIds(data.topic), []),
    rejectGroup: (data) => applySuggestion([], pendingDocIds(data.topic)),
  });
}

function injectSuggestionChips() {
  if (!el.libraryGrid) return;
  const map = suggestionDocMap(suggestionPayload);
  el.libraryGrid.querySelectorAll(".doc-card[data-id]").forEach((card) => {
    const suggestion = map[card.dataset.id];
    if (!suggestion) return;
    const markup = suggestionChipHtml({
      documentId: card.dataset.id, topic: suggestion.topic, status: suggestion.status,
    }, esc);
    if (!markup) return;
    const holder = document.createElement("div");
    holder.innerHTML = markup;
    const chip = holder.firstElementChild;
    if (!chip) return;
    (card.querySelector(".doc-meta") || card).appendChild(chip);
  });
  wireSuggestionChips(el.libraryGrid, (docId) => applySuggestion([docId], []));
}

async function generateSuggestions() {
  if (state.busy) return;
  state.busy = true;
  showToast("正在生成归类建议…");
  try {
    await api("/api/collections/suggestions", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: false }),
    });
    await renderLibrary();
    showToast("归类建议已生成", "ok");
  } catch (e) {
    showToast("生成归类建议失败：" + e.message, "err");
  }
  state.busy = false;
}

async function applySuggestion(accept, reject) {
  if (state.busy) return;
  if (!accept.length && !reject.length) return;
  state.busy = true;
  try {
    // Always carry an explicit accept list (``[]`` for reject-only): the server
    // treats a missing accept as "write nothing", never as "apply everything".
    const body = suggestionApplyBody(accept, reject);
    await api("/api/collections/suggestions/apply", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    showToast(accept.length ? `已归入 ${accept.length} 篇的自动集合` : `已忽略 ${reject.length} 条建议`, "ok");
    await renderLibrary();
  } catch (e) {
    showToast("归类建议操作失败：" + e.message, "err");
  }
  state.busy = false;
}

function renderSkeleton() {
  const card = `
    <div class="doc-card doc-card-skeleton" aria-hidden="true">
      <div class="thumb skeleton-block"></div>
      <div class="doc-meta">
        <div class="skeleton-line wide"></div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line short"></div>
      </div>
    </div>`;
  el.libraryGrid.innerHTML = card.repeat(SKELETON_COUNT);
}

function installThumbnailLazyLoading(root) {
  if (thumbnailLoader) thumbnailLoader.disconnect();
  const makeObserver = typeof IntersectionObserver === "function"
    ? (callback) => new IntersectionObserver(callback, { rootMargin: "0px", threshold: 0.01 })
    : null;
  thumbnailLoader = createThumbnailLoader({
    makeObserver,
    load: (img) => {
      const src = img.dataset.src;
      if (src) {
        img.addEventListener("error", () => img.classList.add("doc-thumb-error"), { once: true });
        img.src = src;
      }
      img.removeAttribute("data-src");
    },
  });
  root.querySelectorAll("img.doc-thumb[data-src]").forEach((img) => {
    thumbnailLoader.observe(img);
  });
}

async function quickReparse(id) {
  if (state.busy) return;
  state.busy = true;
  try {
    await api(`/api/documents/${encodeURIComponent(id)}/reparse`, { method: "POST" });
    showToast("已发起重新解析，完成后卡片会更新", "ok");
  } catch (e) {
    showToast("发起重新解析失败：" + e.message, "err");
  }
  state.busy = false;
}

async function quickDelete(id) {
  try {
    await api(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
    showToast("文档已删除", "ok");
    await renderLibrary();
  } catch (e) {
    showToast("删除失败：" + e.message, "err");
  }
}

export function renderLibraryRoute(route) {
  state.libraryTag = route.tag || null;
  state.libraryTopic = route.topic || null;
  state.libraryCollection = route.collection || null;
  state.libraryFilter = route.filter || "all";
  if (route.collection) {
    state.libraryTag = null;
    state.libraryTopic = null;
    state.libraryFilter = "all";
  }
  if (route.tag || route.topic) {
    state.libraryCollection = null;
    state.libraryFilter = "all";
  }
  renderLibrary();
}

async function renderLibrary() {
  el.libraryZone.classList.remove("hidden");
  applyDensity(state.libraryDensity);
  renderSkeleton();
  let docs = [];
  await loadSuggestions();
  renderSuggestionSection();
  const params = new URLSearchParams();
  if (state.libraryCollection) params.set("collection_id", state.libraryCollection);
  if (state.libraryTag) params.set("tag", state.libraryTag);
  if (state.libraryTopic) params.set("topic", state.libraryTopic);
  const query = params.toString() ? `?${params.toString()}` : "";
  try { docs = await api(`/api/documents${query}`); }
  catch (e) { showToast("加载文档库失败：" + e.message, "err"); }
  docs = filterLibraryDocuments(docs);
  el.libraryCount.textContent = docs.length ? `共 ${docs.length} 份` : "";
  if (el.libraryFilterLabel) {
    el.libraryFilterLabel.textContent = state.libraryTopic
      ? `主题：${state.libraryTopic}`
      : state.libraryTag ? `标签：#${state.libraryTag}` : "";
  }
  el.libraryEmpty.classList.toggle("hidden", docs.length > 0);
  el.libraryGrid.innerHTML = docs.map((d) => cardHtml(d, esc)).join("");
  wireCardActions(el.libraryGrid, {
    open: (id) => go(`#doc/${encodeURIComponent(id)}`),
    confirmDelete: () => window.confirm(DELETE_CONFIRM),
    remove: (id) => quickDelete(id),
    confirmReparse: () => window.confirm(REPARSE_CONFIRM),
    reparse: (id) => quickReparse(id),
  });
  injectSuggestionChips();
  installThumbnailLazyLoading(el.libraryGrid);
  syncLibraryFilters();
  await refreshCollectionTree();
}

function syncLibraryFilters() {
  if (!el.libraryFilters) return;
  el.libraryFilters.querySelectorAll("button[data-library-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.libraryFilter === state.libraryFilter);
  });
}

function filterLibraryDocuments(docs) {
  if (state.libraryFilter === "recent") return docs.slice(0, 12);
  if (state.libraryFilter === "all") return docs;
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const start = new Date(now);
  start.setDate(start.getDate() - (state.libraryFilter === "week" ? 6 : 0));
  const lower = start.toISOString().slice(0, 10);
  return docs.filter((doc) => {
    const value = doc.metadata && doc.metadata.import_time && doc.metadata.import_time.value;
    const day = value ? String(value).slice(0, 10) : "";
    return state.libraryFilter === "today" ? day === today : day >= lower && day <= today;
  });
}

/* Filter chips and the density switch write to the URL / localStorage so
   navigation state and the rendered grid agree after a reload. */
export function wireLibraryFilters() {
  if (el.libraryFilters) {
    el.libraryFilters.querySelectorAll("button[data-library-filter]").forEach((button) => {
      button.addEventListener("click", () => go(libraryHash({ filter: button.dataset.libraryFilter })));
    });
  }
  if (el.libraryDensity) {
    el.libraryDensity.querySelectorAll("button[data-density]").forEach((button) => {
      button.addEventListener("click", () => applyDensity(button.dataset.density));
    });
  }
}

wireLibraryFilters();
registerView("library", renderLibraryRoute);
