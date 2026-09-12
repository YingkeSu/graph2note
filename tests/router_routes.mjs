// Node unit test for the U1 hash router (pure functions, no browser).
//
// `router.js` is imported directly; `state.js` only touches
// `document.querySelector` at import time, so a tiny DOM stub is enough.
// Run: node tests/router_routes.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

globalThis.document = {
  querySelector: () => null,
  createElement: () => ({ textContent: "", innerHTML: "" }),
};
globalThis.location = { hash: "#library" };

const here = path.dirname(fileURLToPath(import.meta.url));
const routerPath = path.join(here, "..", "graph2note", "webstatic", "js", "router.js");
const router = await import(pathToFileURL(routerPath).href);
const { parseHash, libraryHash, registerView, onRender, render } = router;

// ---- 1) every view + sub-route is directly addressable --------------------
assert.deepStrictEqual(parseHash("#library"), { name: "library" });
assert.deepStrictEqual(parseHash(""), { name: "library" });
assert.deepStrictEqual(parseHash("#doc/d%201"), { name: "doc", id: "d 1" });
assert.deepStrictEqual(parseHash("#timeline/week"), { name: "timeline", group: "week" });
assert.deepStrictEqual(parseHash("#timeline/day"), { name: "timeline", group: "day" });
assert.deepStrictEqual(parseHash("#timeline"), { name: "timeline", group: "day" });
assert.deepStrictEqual(parseHash("#graph"), { name: "graph" });
assert.deepStrictEqual(parseHash("#dashboard"), { name: "dashboard" });
assert.deepStrictEqual(parseHash("#inbox"), { name: "inbox" });
assert.deepStrictEqual(parseHash("#settings"), { name: "settings" });
assert.deepStrictEqual(parseHash("#tags"), { name: "tags" });
assert.deepStrictEqual(parseHash("#ask"), { name: "ask" });
// legacy alias: U1 bookmarks / P3 panel jump to #pdf-search -> ask view
assert.deepStrictEqual(parseHash("#pdf-search"), { name: "ask" });
assert.deepStrictEqual(parseHash("#vault-export"), { name: "vault-export" });
assert.deepStrictEqual(parseHash("#upload"), { name: "upload" });

// ---- 2) library filters live in the URL (nav state == URL) ----------------
assert.deepStrictEqual(parseHash("#library/collection/c1"), { name: "library", collection: "c1" });
assert.deepStrictEqual(parseHash("#library/tag/%E9%87%8D%E7%82%B9"), { name: "library", tag: "重点" });
assert.deepStrictEqual(parseHash("#library/topic/%E6%95%B0%E5%AD%A6"), { name: "library", topic: "数学" });
assert.deepStrictEqual(parseHash("#library/filter/week"), { name: "library", filter: "week" });

assert.strictEqual(libraryHash({}), "#library");
assert.strictEqual(libraryHash({ filter: "all" }), "#library");
assert.strictEqual(libraryHash({ filter: "today" }), "#library/filter/today");
assert.strictEqual(parseHash(libraryHash({ collection: "a b" })).collection, "a b");
assert.strictEqual(parseHash(libraryHash({ tag: "重点" })).tag, "重点");
assert.strictEqual(parseHash(libraryHash({ topic: "数学" })).topic, "数学");
assert.strictEqual(parseHash(libraryHash({ filter: "week" })).filter, "week");

// ---- 3) render() dispatches by URL and fires the shell hook ---------------
const rendered = [];
const hooked = [];
registerView("library", (route) => rendered.push(["library", route]));
registerView("timeline", (route) => rendered.push(["timeline", route]));
onRender((route) => hooked.push(route.name));

location.hash = "#timeline/week";
render();
assert.deepStrictEqual(rendered.at(-1), ["timeline", { name: "timeline", group: "week" }]);
assert.strictEqual(hooked.at(-1), "timeline");

location.hash = "#library/filter/today";
render();
assert.deepStrictEqual(rendered.at(-1), ["library", { name: "library", filter: "today" }]);
assert.strictEqual(hooked.at(-1), "library");

// unknown hash falls back to the library view (never a blank page)
location.hash = "#does-not-exist";
render();
assert.strictEqual(rendered.at(-1)[0], "library");

console.log("router_routes: all assertions passed ✓");
