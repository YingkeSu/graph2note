// Node contract test for the issue-02 collection suggestion review UI.
//
// `collection_suggestions.js` has no imports and touches no DOM at load time, so
// it runs in plain Node: payload normalisation, group markup, the empty/done
// states, the card chip, and click dispatch.  Run:
//   node tests/collection_suggestions.mjs
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const modulePath = path.join(
  here, "..", "graph2note", "webstatic", "js", "collection_suggestions.js",
);
const mod = await import(pathToFileURL(modulePath).href);
const {
  normalizeSuggestions, suggestionDocMap, suggestionsHtml, suggestionChipHtml,
  wireSuggestionActions, wireSuggestionChips, SUGGESTION_EMPTY_TEXT,
  SUGGESTION_DONE_TEXT,
} = mod;

const escapeHtml = (value) => String(value == null ? "" : value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const payload = {
  status: "ok",
  model: "stub-model",
  total_tokens: 362,
  candidate_count: 4,
  topics: ["控制理论", "概率论"],
  new_collections: ["概率论"],
  groups: [
    {
      topic: "控制理论",
      collection_id: "控制理论",
      document_count: 2,
      documents: [
        { document_id: "doc-a", title: "传递函数", summary: "系统建模", status: "pending" },
        { document_id: "doc-b", title: "闭环极点", summary: "稳定性", status: "confirmation_required" },
      ],
    },
    {
      topic: "概率论",
      collection_id: "概率论",
      document_count: 2,
      documents: [
        { document_id: "doc-c", title: "分布", summary: "常见分布", status: "pending" },
        { document_id: "doc-d", title: "已归", summary: "", status: "already" },
      ],
    },
  ],
};

// ---- 1) normalisation + pending accounting --------------------------------
const view = normalizeSuggestions(payload);
assert.strictEqual(view.status, "ok");
assert.strictEqual(view.pendingCount, 3, "pending + confirmation_required");
assert.strictEqual(view.confirmationCount, 1);
assert.strictEqual(view.totalTokens, 362);
assert.deepStrictEqual(view.topics, ["控制理论", "概率论"]);
assert.strictEqual(normalizeSuggestions({}).status, "none");
assert.strictEqual(normalizeSuggestions(null).pendingCount, 0);

const docMap = suggestionDocMap(payload);
assert.strictEqual(docMap["doc-a"].topic, "控制理论");
assert.strictEqual(docMap["doc-b"].status, "confirmation_required");
assert.ok(!("doc-d" in docMap), "already-membered docs get no chip");

// ---- 2) group markup ------------------------------------------------------
const html = suggestionsHtml(payload, escapeHtml);
assert.ok(html.includes("归类建议"), "section heading");
assert.ok(html.includes("3 篇待确认"), "pending count");
assert.ok(html.includes("1 篇手工归类需显式确认"), "manual confirmation count");
assert.ok(html.includes('data-suggestion-action="generate"'), "regenerate button");
assert.ok(html.includes('data-suggestion-action="acceptGroup"'), "group accept");
assert.ok(html.includes('data-suggestion-action="rejectGroup"'), "group reject");
assert.ok(html.includes('data-suggestion-action="accept"'), "per-document accept");
assert.ok(html.includes('data-suggestion-action="reject"'), "per-document reject");
assert.ok(html.includes('data-topic="控制理论"') && html.includes("传递函数"), "group renders docs");
assert.ok(html.includes("需确认"), "manual document flagged");
assert.ok(!html.includes("已归"), "already-membered rows are not shown");
assert.ok(html.includes("token 362"), "token usage surfaced");

// ---- 3) empty states ------------------------------------------------------
assert.ok(suggestionsHtml({ status: "none" }, escapeHtml).includes(SUGGESTION_EMPTY_TEXT));
assert.ok(suggestionsHtml({ status: "ok", groups: [] }, escapeHtml).includes(SUGGESTION_EMPTY_TEXT));
const alreadyOnly = {
  status: "ok",
  groups: [{ topic: "控制理论", collection_id: "控制理论",
    documents: [{ document_id: "doc-a", status: "already" }] }],
};
const done = suggestionsHtml(alreadyOnly, escapeHtml);
assert.ok(done.includes(SUGGESTION_DONE_TEXT), "safe empty state when nothing is pending");
assert.ok(done.includes('data-suggestion-action="generate"'), "regenerate stays available");

// escaping: an untrusted title never becomes markup
const escaped = suggestionsHtml({
  status: "ok",
  groups: [{ topic: "<b>x</b>", collection_id: "x",
    documents: [{ document_id: "d", title: "<img src=x onerror=1>", status: "pending" }] }],
}, escapeHtml);
assert.ok(!escaped.includes("<img src=x"), "title escaped");
assert.ok(!escaped.includes("<b>x</b>"), "topic escaped");

// ---- 4) card chip ---------------------------------------------------------
const chip = suggestionChipHtml({ documentId: "doc-a", topic: "控制理论", status: "pending" }, escapeHtml);
assert.ok(chip.includes("doc-collection-chip"), "chip class");
assert.ok(chip.includes('data-suggestion-chip'), "chip marker");
assert.ok(chip.includes('data-document-id="doc-a"'), "chip carries the document id");
assert.ok(chip.includes('data-topic="控制理论"'), "chip carries the topic");
assert.ok(chip.includes("建议集合：控制理论"), "chip label");
assert.strictEqual(suggestionChipHtml(null, escapeHtml), "");
const confirmChip = suggestionChipHtml(
  { documentId: "doc-b", topic: "控制理论", status: "confirmation_required" }, escapeHtml);
assert.ok(confirmChip.includes("需确认"), "manual chip asks for confirmation");

// ---- 5) click dispatch (tiny fake DOM) ------------------------------------
class FakeElement {
  constructor(tag, { dataset = {} } = {}) {
    this.tagName = tag.toUpperCase();
    this.dataset = { ...dataset };
    this.children = [];
    this.listeners = {};
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatch(type, event = {}) {
    (this.listeners[type] || []).forEach((fn) => fn(event));
  }
  querySelectorAll(selector) {
    const match = (node) => {
      if (!selector.startsWith("[") || !selector.endsWith("]")) return false;
      const attr = selector.slice(1, -1);
      if (!attr.startsWith("data-")) return false;
      const key = attr.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      return Object.prototype.hasOwnProperty.call(node.dataset, key);
    };
    const found = [];
    const walk = (node) => node.children.forEach((child) => {
      if (match(child)) found.push(child);
      walk(child);
    });
    walk(this);
    return found;
  }
}

const root = new FakeElement("div");
const accept = new FakeElement("button", {
  dataset: { suggestionAction: "accept", documentId: "doc-a", topic: "控制理论" },
});
const reject = new FakeElement("button", {
  dataset: { suggestionAction: "reject", documentId: "doc-c", topic: "概率论" },
});
const generate = new FakeElement("button", { dataset: { suggestionAction: "generate" } });
const chipNode = new FakeElement("span", {
  dataset: { suggestionChip: "", documentId: "doc-b", topic: "控制理论" },
});
root.children.push(accept, reject, generate, chipNode);

const calls = { accept: [], reject: [], generate: 0, chip: [] };
const stop = { preventDefault() {}, stopPropagation() {} };
wireSuggestionActions(root, {
  generate: () => { calls.generate += 1; },
  accept: (data) => calls.accept.push(data.documentId),
  reject: (data) => calls.reject.push(data.documentId),
});
wireSuggestionChips(root, (documentId, topic) => calls.chip.push([documentId, topic]));

accept.dispatch("click", stop);
reject.dispatch("click", stop);
generate.dispatch("click", stop);
assert.deepStrictEqual(calls.accept, ["doc-a"]);
assert.deepStrictEqual(calls.reject, ["doc-c"]);
assert.strictEqual(calls.generate, 1);

chipNode.dispatch("click", stop);
chipNode.dispatch("keydown", { key: "Enter", ...stop });
assert.deepStrictEqual(calls.chip, [["doc-b", "控制理论"], ["doc-b", "控制理论"]]);

// wiring twice must not double-fire (the dataset guard)
wireSuggestionActions(root, { generate: () => { calls.generate += 1; } });
generate.dispatch("click", stop);
assert.strictEqual(calls.generate, 2, "second wiring does not re-bind");

console.log("collection_suggestions: all assertions passed ✓");
