/* graph2note — Library view (document grid).  U1: only the head + grid + empty
   state live here; collection tree -> sidebar, tag vocabulary -> #tags,
   PDF search/Q&A -> #pdf-search. */
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { go, registerView, libraryHash } from "../router.js";
import { showToast, refreshCollectionTree } from "../ui.js";

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
  el.libraryGrid.innerHTML = "";
  let docs = [];
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
  for (const d of docs) {
    const card = document.createElement("div");
    card.className = "doc-card";
    card.dataset.id = d.document_id;
    card.innerHTML = `
      <div class="thumb"><img loading="lazy" alt="" data-src="/api/documents/${encodeURIComponent(d.document_id)}/preprocessed"></div>
      <div class="doc-meta">
        <div class="doc-title">${esc(d.title)}</div>
        <div class="doc-time dim">更新 ${esc((d.updated_at || "").replace("T", " "))}${d.version_count > 1 ? ` · ${d.version_count} 版` : ""}</div>
      </div>`;
    card.addEventListener("click", () => go(`#doc/${encodeURIComponent(d.document_id)}`));
    el.libraryGrid.appendChild(card);
  }
  syncLibraryFilters();
  await refreshCollectionTree();
  // lazy-load thumbnails
  requestAnimationFrame(() => {
    el.libraryGrid.querySelectorAll("img[data-src]").forEach((img) => {
      img.src = img.dataset.src;
      img.removeAttribute("data-src");
      img.onerror = () => { img.remove(); };
    });
  });
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

/* Filter chips write to the URL so navigation state and history agree. */
export function wireLibraryFilters() {
  if (!el.libraryFilters) return;
  el.libraryFilters.querySelectorAll("button[data-library-filter]").forEach((button) => {
    button.addEventListener("click", () => go(libraryHash({ filter: button.dataset.libraryFilter })));
  });
}

registerView("library", renderLibraryRoute);
