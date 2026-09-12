/* graph2note — first-class Q&A conversation view (P2).

   The PDF Q&A used to live as a small form inside the Library screen (U1 moved
   it to the temporary `#pdf-search` view).  P2 promotes it to a sidebar
   first-class view (`#ask`) that consumes the P1 multi-turn session API:

   - scope picker (default: all imported PDFs) + explicit "新会话" button,
   - bubble conversation (user right / assistant left) with citation chips
     `[PDF name · p12]` that jump to the source page,
   - per-turn waiting / error / retry states (never a full-screen block),
   - the current session is remembered in ``localStorage`` and restored from the
     P1 on-disk session on reload; old sessions stay on disk.

   Cross-view entry contract (consumed by P3's unified search panel):
   - exported ``prefillAsk(question, { navigate })``,
   - window event ``graph2note:ask`` with ``detail.question``,
   - ``sessionStorage["graph2note.pendingAsk"]`` read on view entry.
*/
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { registerView } from "../router.js";
import { esc } from "../utils.js";
import { showToast } from "../ui.js";
import { loadPdfScopeOptions } from "./pdf.js";
import {
  ASK_PREFILL_EVENT,
  ASK_ROUTE,
  ASK_SESSION_STORAGE_KEY,
  PENDING_ASK_KEY,
  buildAskPayload,
  renderConversationHtml,
  sessionToTurns,
  statusLabel,
  turnFromResponse,
} from "../ask_core.js";

/* ---------- helpers ---------- */

function newSessionId() {
  if (window.crypto && typeof crypto.randomUUID === "function")
    return "qa-" + crypto.randomUUID();
  return "qa-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

function readStoredSessionId() {
  try { return localStorage.getItem(ASK_SESSION_STORAGE_KEY) || ""; } catch (_) { return ""; }
}

function storeSessionId(sessionId) {
  try { localStorage.setItem(ASK_SESSION_STORAGE_KEY, sessionId); } catch (_) { /* ignore */ }
}

function clearStoredSessionId() {
  try { localStorage.removeItem(ASK_SESSION_STORAGE_KEY); } catch (_) { /* ignore */ }
}

function currentScopeKey() {
  return el.askScope ? (el.askScope.value || "") : "";
}

function setStatus(text) {
  if (el.pdfQaStatus) el.pdfQaStatus.textContent = text || "";
}

function formatTime(value) {
  if (!value) return "";
  const ms = Number(value) * 1000;
  if (!Number.isFinite(ms)) return "";
  try { return new Date(ms).toLocaleString(); } catch (_) { return ""; }
}

function setComposerBusy(busy) {
  state.askBusy = busy;
  // Keep the input usable (the waiting state is per turn, not a full-screen
  // block); only the submit button is disabled while a turn is in flight.
  if (el.pdfQaForm) {
    const submit = el.pdfQaForm.querySelector('button[type="submit"]');
    if (submit) submit.disabled = busy;
  }
}

function nextTurnIndex() {
  return state.pdfQaHistory.reduce((max, t) => Math.max(max, Number(t.index) || 0), 0) + 1;
}

/* ---------- conversation rendering ---------- */

function renderConversation() {
  const turns = state.pdfQaHistory || [];
  if (el.pdfQaHistory) {
    el.pdfQaHistory.innerHTML = renderConversationHtml(turns);
  }
  if (el.askEmpty) el.askEmpty.classList.toggle("hidden", turns.length > 0);
  if (el.pdfQaHistory) {
    const last = el.pdfQaHistory.lastElementChild;
    if (last && typeof last.scrollIntoView === "function") {
      last.scrollIntoView({ block: "end" });
    }
  }
}

function statusLine(turn) {
  const bits = [`第 ${turn.index} 轮`, statusLabel(turn.status)];
  if (turn.status !== "pending" && turn.status !== "error") bits.push(`检索 ${turn.retrieved} 条`);
  if (turn.model) bits.push(turn.model);
  return bits.join(" · ");
}

/* ---------- session lifecycle ---------- */

function applyScopeValue(pdfIds) {
  const ids = Array.isArray(pdfIds) ? pdfIds : [];
  if (!el.askScope) return;
  const wanted = ids.length === 1 ? ids[0] : "";
  if ([...el.askScope.options].some((opt) => opt.value === wanted)) {
    el.askScope.value = wanted;
  }
}

function applySession(session) {
  state.pdfQaSessionId = session.session_id;
  state.pdfQaScopeKey = currentScopeKey();
  state.pdfQaHistory = sessionToTurns(session);
  applyScopeValue(session.scope ? session.scope.pdf_ids : []);
  state.pdfQaScopeKey = currentScopeKey();
  storeSessionId(session.session_id);
  renderConversation();
}

/* Explicit new topic: fresh session id, empty conversation.  The previous
   session stays on disk (and in the history list). */
export function newSession(options = {}) {
  state.pdfQaSessionId = newSessionId();
  state.pdfQaScopeKey = currentScopeKey();
  state.pdfQaHistory = [];
  storeSessionId(state.pdfQaSessionId);
  renderConversation();
  if (options.notice !== false) {
    setStatus(options.notice || "已开启新会话（历史会话保留）。");
  }
  void refreshSessionList();
  return state.pdfQaSessionId;
}

async function loadSession(sessionId) {
  const session = await api(`/api/pdf/ask/sessions/${encodeURIComponent(sessionId)}`);
  applySession(session);
  return session;
}

async function restoreOrStart() {
  const saved = readStoredSessionId();
  if (saved) {
    try {
      const session = await loadSession(saved);
      setStatus(session.turn_count
        ? `已恢复上次会话（${session.turn_count} 轮）。`
        : "已恢复上次会话（空）。");
      return;
    } catch (_) {
      // the session expired or was evicted: fall through to the most recent one
      clearStoredSessionId();
    }
  }
  // No usable stored id (fresh browser/storage cleared): continue the most
  // recently persisted session so a restart never silently drops the chat.
  try {
    const data = await api("/api/pdf/ask/sessions");
    const recent = (data.sessions || [])[0];
    if (recent) {
      const session = await loadSession(recent.session_id);
      setStatus(`已恢复最近会话（${session.turn_count} 轮）。`);
      return;
    }
  } catch (_) { /* ignore and start fresh */ }
  newSession({ notice: false });
  setStatus("输入问题开始一段可续问的会话。");
}

/* ---------- history session list (optional AC) ---------- */

function renderSessionList() {
  if (!el.askSessions) return;
  const sessions = state.askSessions || [];
  if (el.askSessionsCount) el.askSessionsCount.textContent = sessions.length ? `${sessions.length} 段` : "";
  if (!sessions.length) {
    el.askSessions.innerHTML = `<span class="dim">暂无历史会话</span>`;
    return;
  }
  el.askSessions.innerHTML = sessions.map((s) => {
    const active = s.session_id === state.pdfQaSessionId;
    const scope = s.scope && s.scope.kind !== "all" && s.scope.pdf_ids
      ? `${s.scope.pdf_ids.length} 个 PDF`
      : "全部 PDF";
    return `<button class="ask-session ${active ? "active" : ""}" type="button"`
      + ` data-session-id="${esc(s.session_id)}">`
      + `<span class="ask-session-title">${esc(s.turn_count)} 轮 · ${esc(scope)}</span>`
      + `<span class="dim">${esc(formatTime(s.updated_at))}</span>`
      + (active ? `<span class="ask-session-current">当前</span>` : "")
      + `</button>`;
  }).join("");
}

async function refreshSessionList() {
  if (!el.askSessions) return;
  try {
    const data = await api("/api/pdf/ask/sessions");
    state.askSessions = data.sessions || [];
  } catch (_) {
    state.askSessions = [];
  }
  renderSessionList();
}

async function openSession(sessionId) {
  if (sessionId === state.pdfQaSessionId) return;
  try {
    const session = await loadSession(sessionId);
    setStatus(`已载入会话（${session.turn_count} 轮）。`);
    await refreshSessionList();
  } catch (e) {
    showToast("载入会话失败：" + e.message, "err");
  }
}

/* ---------- asking ---------- */

async function sendTurn(turn) {
  turn.status = "pending";
  turn.error = "";
  renderConversation();
  setStatus(statusLine(turn));
  setComposerBusy(true);
  // P1 contract: the session id is sent on every turn; the scope is the one the
  // session was created with.
  const payload = buildAskPayload(turn.question, state.pdfQaSessionId, state.pdfQaScopeKey);
  try {
    const response = await api("/api/pdf/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    Object.assign(turn, turnFromResponse(response));
    storeSessionId(state.pdfQaSessionId);
    setStatus(statusLine(turn));
    void refreshSessionList();
  } catch (e) {
    if (e.status === 409 || String(e.message || "").includes("新建会话")) {
      newSession({ notice: "检索范围已更改，已开启新会话，请重试本轮。" });
    }
    turn.status = "error";
    turn.error = e.message || "请求失败";
    setStatus("提问失败：" + turn.error);
  } finally {
    setComposerBusy(false);
    renderConversation();
  }
}

function submitQuestion() {
  if (state.askBusy) return;
  const question = (el.pdfQaInput.value || "").trim();
  if (!question) { setStatus("请输入问题。"); return; }
  if (!state.pdfQaSessionId || state.pdfQaScopeKey !== currentScopeKey()) {
    newSession({ notice: false });
  }
  const turn = { index: nextTurnIndex(), question, status: "pending" };
  state.pdfQaHistory.push(turn);
  el.pdfQaInput.value = "";
  void sendTurn(turn);
}

function retryTurn(index) {
  const turn = (state.pdfQaHistory || []).find((t) => Number(t.index) === Number(index));
  if (turn) void sendTurn(turn);
}

/* ---------- cross-view entry contract (P3 consumes) ---------- */

/* Prefill the composer with a question.  ``navigate !== false`` also switches
   to the Q&A view.  Returns false for an empty question. */
export function prefillAsk(question, options = {}) {
  const q = String(question == null ? "" : question).trim();
  if (!q) return false;
  if (options.navigate !== false && location.hash !== ASK_ROUTE) {
    location.hash = ASK_ROUTE;
  }
  if (el.pdfQaInput) {
    el.pdfQaInput.value = q;
    if (typeof el.pdfQaInput.focus === "function") el.pdfQaInput.focus();
  }
  return true;
}

function applyPendingAsk() {
  let pending = "";
  try { pending = (sessionStorage.getItem(PENDING_ASK_KEY) || "").trim(); } catch (_) { pending = ""; }
  if (!pending) return;
  try { sessionStorage.removeItem(PENDING_ASK_KEY); } catch (_) { /* ignore */ }
  prefillAsk(pending, { navigate: false });
}

/* ---------- view ---------- */

async function bootAskView() {
  if (el.askScope) await loadPdfScopeOptions(el.askScope);
  if (el.pdfSearchScope) await loadPdfScopeOptions(el.pdfSearchScope);
  applyPendingAsk();
  await restoreOrStart();
  await refreshSessionList();
}

function renderAsk() {
  el.askZone.classList.remove("hidden");
  void bootAskView();
}

registerView("ask", renderAsk);
/* Legacy alias: bookmarks, the U1 sidebar entry and P3's panel still jump to
   ``#pdf-search``; it now renders the Q&A view. */
registerView("pdf-search", renderAsk);

/* ---------- wiring (browser only) ---------- */

if (el.pdfQaForm) {
  el.pdfQaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitQuestion();
  });
}
if (el.pdfQaNew) {
  el.pdfQaNew.addEventListener("click", () => newSession());
}
if (el.askScope) {
  el.askScope.addEventListener("change", () => {
    // the server binds a session to its scope: switching scope is a new topic
    newSession({ notice: "检索范围已更改，已开启新会话。" });
  });
}
if (el.pdfQaHistory) {
  el.pdfQaHistory.addEventListener("click", (event) => {
    const button = event.target.closest("[data-ask-retry]");
    if (button) retryTurn(button.dataset.askRetry);
  });
}
if (el.askSessions) {
  el.askSessions.addEventListener("click", (event) => {
    const button = event.target.closest("[data-session-id]");
    if (button) void openSession(button.dataset.sessionId);
  });
}

window.addEventListener(ASK_PREFILL_EVENT, (event) => {
  const detail = (event && event.detail) || {};
  prefillAsk(detail.question, { navigate: detail.navigate !== false });
});
window.addEventListener("hashchange", () => { setTimeout(applyPendingAsk, 0); });

if (window.__g2nAsk === undefined) {
  window.__g2nAsk = {
    prefillAsk,
    newSession,
    applyPendingAsk,
    getSessionId: () => state.pdfQaSessionId,
    route: ASK_ROUTE,
  };
}
