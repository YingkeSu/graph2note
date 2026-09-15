/* graph2note — hash router (U1).
   Single source of truth: the URL.  `render()` derives the view from
   `location.hash`, so direct-open, browser back/forward and in-app nav all
   agree.  Views register themselves here; the router never imports views. */
"use strict";

import { state, hideAll } from "./state.js";

const VIEWS = new Map();
let renderHook = null;
const renderHooks = [];

export function registerView(name, handler) {
  VIEWS.set(name, handler);
}

/* Shell chrome (nav highlight, page title, ...) subscribes here so the router
   stays free of ui imports. */
export function onRender(fn) {
  renderHook = fn;
}

/* P3: additional render observers.  ``onRender`` keeps its single-hook contract
   for the shell; feature modules that only need to react to a route use this so
   they never clobber the shell hook. */
export function subscribeRender(fn) {
  if (typeof fn === "function") renderHooks.push(fn);
}

/* In-app navigation.  Same hash -> force re-render (nav click on active view);
   different hash -> push a history entry so back/forward stay meaningful. */
export function go(route) {
  if (location.hash === route) render();
  else location.hash = route;
}

export function parseHash(hash = location.hash) {
  const raw = (hash || "#library").replace(/^#\/?/, "");
  const [pathPart, query = ""] = raw.split("?");
  const parts = pathPart.split("/");
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
  // P3: explicit paper reading deep link.  `#doc/<id>` also renders the paper
  // view for a paper document (see views/paper.js), so both entry points work.
  if (parts[0] === "paper" && parts[1]) {
    return { name: "paper", id: decodeURIComponent(parts[1]) };
  }
  if (parts[0] === "inbox") return { name: "inbox" };
  if (parts[0] === "settings") return { name: "settings" };
  if (parts[0] === "tags") return { name: "tags" };
  if (parts[0] === "ask") return { name: "ask" };
  // legacy alias: U1 bookmarks and P3's panel still jump to #pdf-search, which
  // now renders the first-class Q&A view.
  if (parts[0] === "pdf-search") return { name: "ask" };
  if (parts[0] === "timeline") return { name: "timeline", group: parts[1] === "week" ? "week" : "day" };
  if (parts[0] === "graph") {
    const params = new URLSearchParams(query);
    const list = (key) => params.getAll(key).flatMap((value) =>
      String(value).split(",").map((item) => item.trim()).filter(Boolean));
    const route = { name: "graph" };
    const sources = list("src");
    const collections = list("set");
    const tags = list("tag");
    const topic = params.get("topic");
    const focus = params.get("focus");
    const clusters = params.get("clusters");
    if (sources.length) route.sources = sources;
    if (collections.length) route.collections = collections;
    if (tags.length) route.tags = tags;
    if (topic) route.topic = topic;
    if (focus) route.focus = focus;
    if (clusters === "collapse" || clusters === "expand") route.clusters = clusters;
    return route;
  }
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

/* Canonical hash for a graph view state (U4).  Sources/collections/tags are
   comma-joined and repeated per key so any combination stays readable and
   shareable; an empty state collapses to the plain `#graph` route the shell
   already used before U4. */
export function graphHash({
  sources, collections, tags, topic, focus, clusters,
} = {}) {
  const params = new URLSearchParams();
  const add = (key, values) => {
    const list = (values == null ? [] : Array.isArray(values) ? values : [values])
      .map((value) => String(value).trim()).filter(Boolean);
    if (list.length) params.set(key, list.join(","));
  };
  add("src", sources);
  add("set", collections);
  add("tag", tags);
  if (topic) params.set("topic", topic);
  if (focus) params.set("focus", focus);
  if (clusters === "collapse" || clusters === "expand") params.set("clusters", clusters);
  const query = params.toString();
  return query ? `#graph?${query}` : "#graph";
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
  renderHooks.forEach((fn) => fn(route));
  const view = VIEWS.get(route.name) || VIEWS.get("library");
  if (view) view(route);
}

export function startRouter() {
  window.addEventListener("hashchange", render);
}
