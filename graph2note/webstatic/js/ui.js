/* graph2note — app shell: toast, sidebar, nav highlight, collection tree,
   global search placeholder (U1).  Views import from here; ui.js depends on
   router.js but router.js never imports ui.js (no cycles). */
"use strict";

import { el, state } from "./state.js";
import { api } from "./api.js";
import { wireWorkspace, syncWorkspace } from "./workspace.js";
import { esc } from "./utils.js";
import { go, render, libraryHash, onRender } from "./router.js";

/* ---------- toast ---------- */

export function showToast(msg, kind = "") {
  el.toast.textContent = msg;
  el.toast.className = "toast " + kind;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.toast.classList.add("hidden"), kind === "err" ? 6000 : 3000);
}

/* Persistent, retryable loading errors. Messages are inserted as text, never HTML. */
export function clearViewError(zone) {
  const previous = zone && zone.querySelector(".view-error");
  if (previous) previous.remove();
}

export function showViewError(zone, message, retry) {
  if (!zone) return;
  clearViewError(zone);
  const panel = document.createElement("div");
  panel.className = "view-error";
  panel.setAttribute("role", "alert");
  const text = document.createElement("span");
  text.textContent = message;
  const button = document.createElement("button");
  button.className = "btn small";
  button.type = "button";
  button.textContent = "重新加载";
  button.addEventListener("click", () => {
    // The loading function clears this panel. Keep focus in the current view.
    document.getElementById("content").focus({ preventScroll: true });
    retry();
  });
  panel.append(text, button);
  zone.prepend(panel);
}

/* ---------- active nav highlight ---------- */

/* doc/paper views belong to the Library section; upload has no sidebar item. */
const NAV_VIEW_ALIAS = { doc: "library", paper: "library" };

export function syncNav(routeName) {
  const view = NAV_VIEW_ALIAS[routeName] || routeName;
  document.querySelectorAll("#sidebar-nav .nav-item, #sidebar-secondary .nav-item")
    .forEach((node) => {
      const active = node.dataset.view === view;
      node.classList.toggle("active", active);
      if (active) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
  document.querySelectorAll(".nav-group").forEach((group) => {
    const active = group.querySelector('.nav-item[aria-current="page"]');
    group.classList.toggle("has-current", Boolean(active));
    // Deep links and browser history reveal the destination's actual location.
    if (active) group.open = true;
  });
}

/* ---------- sidebar collapse ---------- */

const SIDEBAR_KEY = "graph2note.sidebar-collapsed";

function readCollapsed() {
  try {
    const saved = localStorage.getItem(SIDEBAR_KEY);
    if (saved !== null) return saved === "1";
  } catch (_) { /* use the viewport default */ }
  return typeof window.matchMedia === "function" && window.matchMedia("(max-width: 900px)").matches;
}

function applyCollapsed(collapsed) {
  el.appShell.classList.toggle("sidebar-collapsed", collapsed);
  if (el.sidebarToggle) {
    el.sidebarToggle.setAttribute("aria-expanded", String(!collapsed));
    el.sidebarToggle.title = collapsed ? "展开侧栏" : "折叠侧栏";
    el.sidebarToggle.setAttribute("aria-label", el.sidebarToggle.title);
  }
  try { localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0"); } catch (_) { /* ignore */ }
}

/* ---------- global search (P3: unified search panel owns the topbar entry) -------
   The U1 placeholder behaviour moved into /static/search-panel.js, which is
   imported by app.js: ⌘K / the topbar input open the grouped document+PDF panel
   and Esc closes it.  Keep this hook so the shell wiring stays in one place. */

function wireGlobalSearch() {
  /* no-op: see search-panel.js (P3) */
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
      <details class="collection-tree-actions disclosure" data-popover>
        <summary aria-label="管理集合：${esc(item.name)}">更多</summary>
        <div class="collection-actions-panel">
          <button class="tag-action" aria-label="重命名集合：${esc(item.name)}" data-collection-action="rename" data-collection-id="${esc(item.collection_id)}">重命名</button>
          <button class="tag-action" aria-label="删除集合：${esc(item.name)}" data-collection-action="delete" data-collection-id="${esc(item.collection_id)}">删除集合</button>
        </div>
      </details>
    </span>`).join("") : `<span class="dim">暂无集合</span>`;

  el.collectionTree.querySelectorAll("button.collection-open").forEach((button) => {
    button.addEventListener("click", () => go(libraryHash({ collection: button.dataset.collectionId })));
  });
  if (selected) {
    const collection = collections.find((item) => item.collection_id === selected);
    const browser = document.getElementById("collection-browser");
    if (browser) browser.open = true;
    if (collection && el.libraryFilterLabel) el.libraryFilterLabel.textContent = `集合：${collection.name}`;
  }
  el.collectionTree.querySelectorAll("button[data-collection-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const cid = button.dataset.collectionId;
      const menu = button.closest("details");
      if (menu) {
        menu.open = false;
        menu.querySelector("summary").focus();
      }
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
      const disclosure = document.getElementById("collection-create-disclosure");
      if (disclosure) {
        disclosure.open = false;
        disclosure.querySelector("summary").focus();
      }
    } catch (e) { showToast("新建集合失败：" + e.message, "err"); }
  });
}

/* ---------- boot wiring ---------- */

export function wireShell() {
  applyCollapsed(readCollapsed());
  wireWorkspace();
  wireDisclosures();
  onRender((route) => { syncNav(route.name); syncWorkspace(route); });
  const skipLink = document.querySelector(".skip-link");
  if (skipLink) skipLink.addEventListener("click", (event) => {
    // Keep the active hash route: #content is a focus target, not a view.
    event.preventDefault();
    document.getElementById("content").focus();
  });
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

/* Native disclosures keep secondary controls out of the tab order while closed.
   Popovers also dismiss on outside click, route changes and Escape. */
function wireDisclosures() {
  const close = (details, restoreFocus = false) => {
    details.open = false;
    if (restoreFocus) details.querySelector("summary").focus();
  };
  document.addEventListener("click", (event) => {
    document.querySelectorAll("details[data-popover][open]").forEach((details) => {
      if (!details.contains(event.target)) close(details);
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const details = event.target.closest("details[open]");
    if (details && details.matches(".nav-group, .disclosure, .sidebar-collections")) {
      event.preventDefault();
      close(details, true);
    }
  });
  window.addEventListener("hashchange", () => {
    document.querySelectorAll("details[data-popover][open]").forEach((details) => {
      close(details, details.contains(document.activeElement));
    });
  });
  document.getElementById("collection-create-disclosure")?.addEventListener("toggle", (event) => {
    if (event.target.open) el.collectionCreateInput.focus();
  });
}
