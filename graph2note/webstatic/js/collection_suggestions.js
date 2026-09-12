/* graph2note — collection suggestion review (auto-organization issue 02).

   Pure, DOM-light helpers for the Library "归类建议" section and the document
   card "建议集合" chip.  Kept free of imports (like library_cards.js) so the
   Node contract test (tests/collection_suggestions.mjs) can exercise the markup
   and the click dispatch with a tiny fake DOM.

   Server payload shape (see graph2note.collection_organize.suggestions_payload):
     {status, model, total_tokens, topics, pending_count,
      confirmation_required_count, groups: [{topic, collection_id,
      document_count, documents: [{document_id, title, summary, status}]}]}
*/
"use strict";

export const SUGGESTION_EMPTY_TEXT = "归类建议：尚未生成。";
export const SUGGESTION_DONE_TEXT = "暂无待确认的归类建议 ✓";
export const PENDING_STATUSES = Object.freeze(["pending", "confirmation_required"]);

function itemStatus(item) {
  return String((item && item.status) || "pending");
}

export function isPending(item) {
  return PENDING_STATUSES.includes(itemStatus(item));
}

/* Normalise a raw API payload into {status, groups, topics, ...} with only
   genuinely actionable documents counted as pending. */
export function normalizeSuggestions(payload) {
  const value = payload && typeof payload === "object" ? payload : {};
  const rawGroups = Array.isArray(value.groups) ? value.groups : [];
  const groups = rawGroups
    .map((group) => ({
      topic: String(group.topic || "").trim(),
      collectionId: String(group.collection_id || group.topic || "").trim(),
      documentCount: Number(group.document_count || 0),
      documents: (Array.isArray(group.documents) ? group.documents : []).map((doc) => ({
        documentId: String(doc.document_id || ""),
        title: String(doc.title || doc.document_id || ""),
        summary: String(doc.summary || ""),
        status: itemStatus(doc),
      })),
    }))
    .filter((group) => group.topic && group.documents.length > 0);
  const pending = groups.reduce(
    (total, group) => total + group.documents.filter(isPending).length, 0);
  const confirmation = groups.reduce(
    (total, group) => total
      + group.documents.filter((doc) => doc.status === "confirmation_required").length, 0);
  const status = value.status === "none" || groups.length === 0 ? "none" : "ok";
  return {
    status,
    groups,
    topics: Array.isArray(value.topics) ? value.topics.map(String) : groups.map((g) => g.topic),
    model: value.model ? String(value.model) : "",
    totalTokens: Number(value.total_tokens || 0),
    candidateCount: Number(value.candidate_count || 0),
    pendingCount: pending,
    confirmationCount: confirmation,
    newCollections: Array.isArray(value.new_collections)
      ? value.new_collections.map(String) : [],
  };
}

/* document_id -> first suggestion (topic/collection/status/summary). */
export function suggestionDocMap(payload) {
  const view = normalizeSuggestions(payload);
  const map = {};
  view.groups.forEach((group) => {
    group.documents.forEach((doc) => {
      if (!doc.documentId || map[doc.documentId]) return;
      if (!isPending(doc)) return;
      map[doc.documentId] = {
        topic: group.topic,
        collectionId: group.collectionId,
        status: doc.status,
        summary: doc.summary,
      };
    });
  });
  return map;
}

function docRow(group, doc, esc) {
  const confirm = doc.status === "confirmation_required"
    ? `<span class="suggestion-doc-flag" title="该文档已有手工集合，接受后追加自动归属">需确认</span>` : "";
  return `
      <li class="suggestion-doc" data-document-id="${esc(doc.documentId)}" data-topic="${esc(group.topic)}">
        <span class="suggestion-doc-title">${esc(doc.title)}</span>
        ${doc.summary ? `<span class="suggestion-doc-summary dim">${esc(doc.summary)}</span>` : ""}
        ${confirm}
        <span class="suggestion-doc-actions">
          <button class="tag-action" type="button" data-suggestion-action="accept"
                  data-document-id="${esc(doc.documentId)}" data-topic="${esc(group.topic)}">接受</button>
          <button class="tag-action" type="button" data-suggestion-action="reject"
                  data-document-id="${esc(doc.documentId)}" data-topic="${esc(group.topic)}">忽略</button>
        </span>
      </li>`;
}

function groupBlock(group, esc) {
  const pending = group.documents.filter(isPending);
  if (!pending.length) return "";
  return `
    <div class="suggestion-group" data-topic="${esc(group.topic)}">
      <div class="suggestion-group-head">
        <span class="suggestion-topic">${esc(group.topic)}</span>
        <span class="dim">${pending.length} 篇</span>
        <button class="tag-action" type="button" data-suggestion-action="acceptGroup"
                data-topic="${esc(group.topic)}">整组接受</button>
        <button class="tag-action" type="button" data-suggestion-action="rejectGroup"
                data-topic="${esc(group.topic)}">整组忽略</button>
      </div>
      <ul class="suggestion-docs">
        ${pending.map((doc) => docRow(group, doc, esc)).join("")}
      </ul>
    </div>`;
}

export function suggestionsHtml(payload, esc) {
  const view = normalizeSuggestions(payload);
  const generate = (label) =>
    `<button class="btn small" type="button" data-suggestion-action="generate">${esc(label)}</button>`;
  if (view.status === "none") {
    return `<div class="suggestions-empty"><span class="dim">${esc(SUGGESTION_EMPTY_TEXT)}</span>${generate("生成建议")}</div>`;
  }
  if (!view.pendingCount) {
    return `<div class="suggestions-empty"><span class="dim">${esc(SUGGESTION_DONE_TEXT)}</span>${generate("重新生成")}</div>`;
  }
  const heading = view.confirmationCount
    ? `${view.pendingCount} 篇待确认（含 ${view.confirmationCount} 篇手工归类需显式确认）`
    : `${view.pendingCount} 篇待确认`;
  const meta = [
    view.topics.length ? `${view.topics.length} 个集合` : "",
    view.candidateCount ? `相似候选 ${view.candidateCount} 对` : "",
    view.model ? `model=${view.model}` : "",
    `token ${view.totalTokens}`,
  ].filter(Boolean).join(" · ");
  return `
    <div class="suggestions-head">
      <h3>归类建议 <span class="dim">${esc(heading)}</span></h3>
      <span class="dim suggestions-meta">${esc(meta)}</span>
      ${generate("重新生成")}
    </div>
    <div class="suggestion-groups">${view.groups.map((group) => groupBlock(group, esc)).join("")}</div>`;
}

/* Document-card chip: one-click accept.  Returns "" when no suggestion. */
export function suggestionChipHtml(suggestion, esc) {
  if (!suggestion || !suggestion.topic || !suggestion.documentId) return "";
  const confirm = suggestion.status === "confirmation_required" ? "（需确认）" : "";
  return `<span class="doc-collection-chip" role="button" tabindex="0"`
    + ` data-suggestion-chip data-document-id="${esc(suggestion.documentId)}"`
    + ` data-topic="${esc(suggestion.topic)}"`
    + ` title="建议集合：${esc(suggestion.topic)}${esc(confirm)}">建议集合：${esc(suggestion.topic)}${esc(confirm)}</span>`;
}

/* Dispatch clicks on any [data-suggestion-action] node.  Handlers are keyed by
   the action name and receive (dataset, event); group actions are resolved by
   the caller (which owns the payload). */
export function wireSuggestionActions(root, handlers) {
  if (!root) return;
  root.querySelectorAll("[data-suggestion-action]").forEach((button) => {
    if (button.dataset.suggestionWired === "1") return;
    button.dataset.suggestionWired = "1";
    button.addEventListener("click", (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      const action = button.dataset.suggestionAction;
      const handler = handlers && handlers[action];
      if (typeof handler === "function") handler(button.dataset, event);
    });
  });
}

/* Chips use the same accept action so the card and the review list share one
   code path. */
export function wireSuggestionChips(root, onAccept) {
  if (!root) return;
  root.querySelectorAll("[data-suggestion-chip]").forEach((chip) => {
    const activate = (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      if (event && typeof event.stopPropagation === "function") event.stopPropagation();
      onAccept(chip.dataset.documentId, chip.dataset.topic);
    };
    chip.addEventListener("click", activate);
    chip.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") activate(event);
    });
  });
}
