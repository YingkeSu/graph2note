/* graph2note — pure helpers for the first-class Q&A conversation view (P2).

   No DOM, no imports: everything here is a pure function over plain values, so
   it can be exercised from Node (``tests/ask_view.mjs``) without a browser and
   stays easy to reason about.  ``views/ask.js`` owns the DOM wiring.

   Contract pieces other views (P3 unified search) may rely on:
   - ``ASK_SESSION_STORAGE_KEY`` / ``PENDING_ASK_KEY`` storage keys,
   - ``ASK_PREFILL_EVENT`` window event name,
   - ``renderConversationHtml`` / ``citationChipHtml`` output shape.
*/
"use strict";

/* Persisted current-conversation id (P1 sessions survive a reload). */
export const ASK_SESSION_STORAGE_KEY = "graph2note.askSessionId";
/* Query hand-off slot used by the P3 search panel ("就这些结果提问"). */
export const PENDING_ASK_KEY = "graph2note.pendingAsk";
/* Custom event any module can dispatch on ``window`` to prefill the composer. */
export const ASK_PREFILL_EVENT = "graph2note:ask";
export const ASK_ROUTE = "#ask";

export function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* ---------- request assembly (P1 contract) ---------- */

/* One turn's request body.  ``session_id`` is always carried so the server can
   keep the conversation going; ``pdf_id`` only appears when a scope is picked
   (omitted == "all imported PDFs"). */
export function buildAskPayload(question, sessionId, scopeKey) {
  const payload = {
    question: String(question == null ? "" : question).trim(),
    session_id: sessionId,
  };
  const scope = scopeKey == null ? "" : String(scopeKey);
  if (scope) payload.pdf_id = scope;
  return payload;
}

/* ---------- citations -> chips ---------- */

export function citationName(citation) {
  const c = citation || {};
  if (c.pdf_name) return c.pdf_name;
  // On the single-PDF path the document title is often "<file> · 第N页"; drop
  // that page suffix so the chip reads `[PDF 名 · p12]` instead of repeating it.
  const title = String(c.title || "").replace(/\s*·\s*第\s*\d+\s*页\s*$/, "").trim();
  return title || c.document_id || c.pdf_id || "PDF";
}

export function citationPage(citation) {
  const c = citation || {};
  if (c.page_number !== undefined && c.page_number !== null && c.page_number !== "") {
    const n = Number(c.page_number);
    if (!Number.isNaN(n)) return n;
  }
  if (c.page_index === undefined || c.page_index === null || c.page_index === "") return null;
  const n = Number(c.page_index);
  return Number.isNaN(n) ? null : n + 1;
}

export function citationLabel(citation) {
  const page = citationPage(citation);
  return `[${citationName(citation)} · p${page == null ? "?" : page}]`;
}

/* A citation chip is a link to the source page (same jump path the keyword
   search and issue-11 Q&A already use: ``/api/documents/<id>/source-page``). */
export function citationChipHtml(citation) {
  const c = citation || {};
  const href = c.source_page_url || c.pdf_page_url || "";
  const docId = c.document_id ? `#doc/${encodeURIComponent(c.document_id)}` : "";
  const editor = docId
    ? `<a class="ask-citation-doc" href="${escapeHtml(docId)}">打开校对</a>`
    : "";
  return `<span class="ask-citation-row">`
    + `<a class="ask-citation" href="${escapeHtml(href)}" target="_blank" rel="noopener"`
    + ` data-document-id="${escapeHtml(c.document_id || "")}"`
    + ` data-page-index="${escapeHtml(c.page_index == null ? "" : c.page_index)}"`
    + ` title="打开原 PDF 页">${escapeHtml(citationLabel(c))}</a>`
    + editor
    + `</span>`;
}

/* ---------- turn model ---------- */

export const STATUS_LABELS = {
  answered: "已生成",
  insufficient_evidence: "证据不足",
  timeout: "生成超时",
  model_unavailable: "模型不可用",
  error: "请求失败",
  pending: "生成中",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || status || "";
}

/* Normalise a persisted P1 ``Turn.public()`` (or an in-flight client turn).
   Accepts both the server key ``untrusted_citations`` and the client-side
   ``untrusted`` alias so turns can be re-normalised safely. */
export function normalizeTurn(raw) {
  const t = raw || {};
  return {
    index: Number(t.index || 0),
    question: String(t.question || ""),
    answer: String(t.answer || ""),
    status: String(t.status || "answered"),
    citations: Array.isArray(t.citations) ? t.citations : [],
    untrusted: Array.isArray(t.untrusted_citations) ? t.untrusted_citations
      : (Array.isArray(t.untrusted) ? t.untrusted : []),
    retrieved: Number(t.retrieved || 0),
    model: t.model || null,
    message: String(t.message || ""),
    error: String(t.error || ""),
  };
}

/* Map one ``POST /api/pdf/ask`` response onto a turn entry. */
export function turnFromResponse(response) {
  const r = response || {};
  return {
    index: Number(r.turn_index || 0),
    question: String(r.question || ""),
    answer: String(r.answer || ""),
    status: String(r.status || "answered"),
    citations: Array.isArray(r.citations) ? r.citations : [],
    untrusted: Array.isArray(r.untrusted_citations) ? r.untrusted_citations : [],
    retrieved: Number(r.retrieved || 0),
    model: r.model || null,
    message: String(r.message || ""),
    error: "",
  };
}

/* ``GET /api/pdf/ask/sessions/<id>`` -> turn entries (reload / restore). */
export function sessionToTurns(session) {
  const turns = (session && session.turns) || [];
  return turns.map(normalizeTurn);
}

/* ---------- turn HTML ---------- */

function bodyHtml(turn) {
  const text = turn.answer || turn.message || "（无内容）";
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function citationsHtml(turn) {
  if (!turn.citations.length) return "";
  return `<div class="ask-citations">`
    + turn.citations.map(citationChipHtml).join("")
    + `</div>`;
}

function warningsHtml(turn) {
  const lines = [];
  if (turn.untrusted.length) {
    lines.push(`模型给出的无效引用已忽略：${turn.untrusted.map(escapeHtml).join("、")}`);
  }
  if (!lines.length) return "";
  return `<div class="ask-warn">${lines.join("<br>")}</div>`;
}

function turnMeta(turn) {
  const bits = [`第 ${turn.index} 轮`, statusLabel(turn.status)];
  if (turn.status !== "pending" && turn.status !== "error") {
    bits.push(`检索 ${turn.retrieved} 条`);
  }
  if (turn.model) bits.push(turn.model);
  return `<div class="ask-turn-meta dim">${bits.map(escapeHtml).join(" · ")}</div>`;
}

export function userTurnHtml(turn) {
  const t = normalizeTurn(turn);
  return `<article class="ask-turn ask-turn-user" data-turn-index="${t.index}">`
    + `<div class="ask-bubble ask-bubble-user">${escapeHtml(t.question)}</div>`
    + `</article>`;
}

export function pendingTurnHtml(turn) {
  const t = normalizeTurn({ ...turn, status: "pending" });
  return `<article class="ask-turn ask-turn-assistant ask-pending" data-turn-index="${t.index}">`
    + `<div class="ask-bubble ask-bubble-assistant">`
    + `<span class="ask-spinner" aria-hidden="true"></span>`
    + `<span>正在检索并生成…</span>`
    + `</div>${turnMeta(t)}</article>`;
}

export function errorTurnHtml(turn) {
  const t = normalizeTurn({ ...turn, status: "error" });
  const msg = t.error || t.message || "请求失败";
  return `<article class="ask-turn ask-turn-assistant ask-turn-error" data-turn-index="${t.index}">`
    + `<div class="ask-bubble ask-bubble-assistant">`
    + `<div class="ask-error-msg">提问失败：${escapeHtml(msg)}</div>`
    + `<button class="btn small ask-retry" type="button" data-ask-retry="${t.index}">重试本轮</button>`
    + `</div>${turnMeta(t)}</article>`;
}

export function assistantTurnHtml(turn) {
  const t = normalizeTurn(turn);
  if (t.status === "pending") return pendingTurnHtml(t);
  if (t.status === "error") return errorTurnHtml(t);
  return `<article class="ask-turn ask-turn-assistant" data-turn-index="${t.index}"`
    + ` data-turn-status="${escapeHtml(t.status)}">`
    + `<div class="ask-bubble ask-bubble-assistant">`
    + `<div class="ask-answer">${bodyHtml(t)}</div>`
    + citationsHtml(t)
    + warningsHtml(t)
    + `</div>${turnMeta(t)}</article>`;
}

/* Whole conversation as user/assistant bubble pairs, in order. */
export function renderConversationHtml(turns) {
  return (turns || []).map((turn) => userTurnHtml(turn) + assistantTurnHtml(turn)).join("");
}
