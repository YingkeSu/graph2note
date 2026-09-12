/* graph2note — app shell: toast, sidebar, nav highlight, collection tree,
   global search placeholder (U1).  Views import from here; ui.js depends on
   router.js but router.js never imports ui.js (no cycles). */
"use strict";

import { el, state } from "./state.js";
import { api } from "./api.js";
import { esc } from "./utils.js";
import { go, render, libraryHash, onRender } from "./router.js";

/* ---------- toast ---------- */

export function showToast(msg, kind = "") {
  el.toast.textContent = msg;
  el.toast.className = "toast " + kind;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.toast.classList.add("hidden"), kind === "err" ? 6000 : 3000);
}

/* ---------- active nav highlight ---------- */

/* doc views belong to the Library section; upload has no sidebar item. */
const NAV_VIEW_ALIAS = { doc: "library" };

export function syncNav(routeName) {
  const view = NAV_VIEW_ALIAS[routeName] || routeName;
  document.querySelectorAll("#sidebar-nav .nav-item, #sidebar-secondary .nav-item")
    .forEach((node) => {
      const active = node.dataset.view === view;
      node.classList.toggle("active", active);
      if (active) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
}

/* ---------- sidebar collapse ---------- */

const SIDEBAR_KEY = "graph2note.sidebar-collapsed";

function readCollapsed() {
  try { return localStorage.getItem(SIDEBAR_KEY) === "1"; } catch (_) { return false; }
}

function applyCollapsed(collapsed) {
  el.appShell.classList.toggle("sidebar-collapsed", collapsed);
  if (el.sidebarToggle) {
    el.sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
    el.sidebarToggle.title = collapsed ? "展开侧栏" : "折叠侧栏";
  }
  try { localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0"); } catch (_) { /* ignore */ }
}

/* ---------- global search placeholder (unified search lands in P3) ---------- */

function wireGlobalSearch() {
  if (el.globalSearchForm) {
    el.globalSearchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const q = (el.globalSearchInput.value || "").trim();
      if (!q) return;
      showToast("统一搜索将在 P3 落地；当前可在「问答」视图中检索或提问", "");
    });
  }
  document.addEventListener("keydown", (event) => {
    // placeholder focus behaviour only: ⌘K focuses, Esc blurs/clears.
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      if (el.globalSearchInput) { event.preventDefault(); el.globalSearchInput.focus(); }
    } else if (event.key === "Escape" && document.activeElement === el.globalSearchInput) {
      el.globalSearchInput.blur();
    }
  });
}

/* ---------- sidebar collection tree ---------- */

export async function refreshCollectionTree() {
  if (!el.collectionTree) return;
  let collections = [];
  try { collections = await api("/api/collections"); }
  catch (e) { showToast("加载集合失败：" + e.message, "err"); return; }
  const selected = state.route === "library" ? state.libraryCollection : null;
  el.collectionTree.innerHTML = collections.length ? collections.map((item) => `
    <span class="collection-tree-item ${selected === item.collection_id ? "selected" : ""}">
      <button class="workspace-link collection-open" data-collection-id="${esc(item.collection_id)}">${esc(item.name)} <span class="dim">${item.document_count}</span></button>
      <span class="collection-tree-actions">
        <button class="tag-action" data-collection-action="rename" data-collection-id="${esc(item.collection_id)}">改名</button>
        <button class="tag-action" data-collection-action="delete" data-collection-id="${esc(item.collection_id)}">删除</button>
      </span>
    </span>`).join("") : `<span class="dim">暂无集合</span>`;

  el.collectionTree.querySelectorAll("button.collection-open").forEach((button) => {
    button.addEventListener("click", () => go(libraryHash({ collection: button.dataset.collectionId })));
  });
  el.collectionTree.querySelectorAll("button[data-collection-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const cid = button.dataset.collectionId;
      try {
        if (button.dataset.collectionAction === "delete") {
          await api(`/api/collections/${encodeURIComponent(cid)}`, { method: "DELETE" });
          if (state.libraryCollection === cid) { go("#library"); return; }
        } else {
          const name = window.prompt("集合重命名为？", cid);
          if (!name || name === cid) return;
          await api(`/api/collections/${encodeURIComponent(cid)}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
          });
        }
        await refreshCollectionTree();
        render();
      } catch (e) { showToast("集合操作失败：" + e.message, "err"); }
    });
  });
}

function wireCollectionCreate() {
  if (!el.collectionCreateForm) return;
  el.collectionCreateForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = el.collectionCreateInput.value.trim();
    if (!name) return;
    try {
      await api("/api/collections", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      el.collectionCreateInput.value = "";
      await refreshCollectionTree();
    } catch (e) { showToast("新建集合失败：" + e.message, "err"); }
  });
}

/* ---------- boot wiring ---------- */

export function wireShell() {
  applyCollapsed(readCollapsed());
  onRender((route) => syncNav(route.name));
  if (el.sidebarToggle) {
    el.sidebarToggle.addEventListener("click", () => {
      applyCollapsed(!el.appShell.classList.contains("sidebar-collapsed"));
    });
  }
  // static nav entries carry data-route; dynamic ones wire themselves.
  document.querySelectorAll("[data-route]").forEach((node) => {
    node.addEventListener("click", () => go(node.dataset.route));
  });
  wireGlobalSearch();
  wireCollectionCreate();
}
