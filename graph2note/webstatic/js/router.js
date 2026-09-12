/* graph2note — hash router (U1).
   Single source of truth: the URL.  `render()` derives the view from
   `location.hash`, so direct-open, browser back/forward and in-app nav all
   agree.  Views register themselves here; the router never imports views. */
"use strict";

import { state, hideAll } from "./state.js";

const VIEWS = new Map();
let renderHook = null;

export function registerView(name, handler) {
  VIEWS.set(name, handler);
}

/* Shell chrome (nav highlight, page title, ...) subscribes here so the router
   stays free of ui imports. */
export function onRender(fn) {
  renderHook = fn;
}

/* In-app navigation.  Same hash -> force re-render (nav click on active view);
   different hash -> push a history entry so back/forward stay meaningful. */
export function go(route) {
  if (location.hash === route) render();
  else location.hash = route;
}

export function parseHash(hash = location.hash) {
  const h = (hash || "#library").replace(/^#\/?/, "");
  const parts = h.split("/");
  if (parts[0] === "doc" && parts[1]) {
    const route = { name: "doc", id: decodeURIComponent(parts[1]) };
    // S3 deep link: #doc/<id>/diff[/<versionA>[/<versionB>]] opens the
    // read-only version comparison overlay directly.
    if (parts[2] === "diff") {
      route.compare = true;
      if (parts[3]) route.versionA = decodeURIComponent(parts[3]);
      if (parts[4]) route.versionB = decodeURIComponent(parts[4]);
    } else if (parts[2] === "versions") {
      // S3 deep link: #doc/<id>/versions opens the info side panel (switcher).
      route.panel = true;
    }
    return route;
  }
  if (parts[0] === "inbox") return { name: "inbox" };
  if (parts[0] === "settings") return { name: "settings" };
  if (parts[0] === "tags") return { name: "tags" };
  if (parts[0] === "ask") return { name: "ask" };
  // legacy alias: U1 bookmarks and P3's panel still jump to #pdf-search, which
  // now renders the first-class Q&A view.
  if (parts[0] === "pdf-search") return { name: "ask" };
  if (parts[0] === "timeline") return { name: "timeline", group: parts[1] === "week" ? "week" : "day" };
  if (parts[0] === "graph") return { name: "graph" };
  if (parts[0] === "dashboard") return { name: "dashboard" };
  if (parts[0] === "library" && parts[1] === "topic" && parts[2]) {
    return { name: "library", topic: decodeURIComponent(parts.slice(2).join("/")) };
  }
  if (parts[0] === "library" && parts[1] === "tag" && parts[2]) {
    return { name: "library", tag: decodeURIComponent(parts.slice(2).join("/")) };
  }
  if (parts[0] === "library" && parts[1] === "collection" && parts[2]) {
    return { name: "library", collection: decodeURIComponent(parts.slice(2).join("/")) };
  }
  if (parts[0] === "library" && parts[1] === "filter" && parts[2]) {
    return { name: "library", filter: decodeURIComponent(parts.slice(2).join("/")) };
  }
  if (parts[0] === "upload") return { name: "upload" };
  if (parts[0] === "vault-export") return { name: "vault-export" };
  if (parts[0] === "repair") return { name: "repair" };   // R1 黑图修复报告
  return { name: "library" };
}

/* Canonical hash for a Library filter state (collection / tag / topic / chip).
   Used by the sidebar collection tree and the Library filter chips so that
   navigation state is always reflected in the URL. */
export function libraryHash({ collection, tag, topic, filter } = {}) {
  if (collection) return `#library/collection/${encodeURIComponent(collection)}`;
  if (topic) return `#library/topic/${encodeURIComponent(topic)}`;
  if (tag) return `#library/tag/${encodeURIComponent(tag)}`;
  if (filter && filter !== "all") return `#library/filter/${encodeURIComponent(filter)}`;
  return "#library";
}

export function render() {
  const route = parseHash();
  state.route = route.name;
  hideAll();
  if (renderHook) renderHook(route);
  const view = VIEWS.get(route.name) || VIEWS.get("library");
  if (view) view(route);
}

export function startRouter() {
  window.addEventListener("hashchange", render);
}
