/* graph2note — PDF per-page upload status (issue 08/09) + PDF content search
   (issue 10) + grounded single-turn Q&A (issue 11).

   U1 moved the search/Q&A block out of Library into its own temporary
   `#pdf-search` view, and P1's multi-turn conversation controls (new-session
   button, prior-turn history) are kept in the moved block; the internal
   behaviour below is unchanged apart from no longer sharing the Library zone
   with the document grid. */
"use strict";

import { el, state, hideAll, setBusy } from "../state.js";
import { api } from "../api.js";
import { esc, escapeRe, POLL_MS } from "../utils.js";
import { go, registerView } from "../router.js";
import { showToast } from "../ui.js";
import { showWorking } from "../jobs.js";

/* ---------- PDF content search (issue 10) ---------- */

function pdfScopeLabel(j) {
  const c = j.counts || {};
  const total = j.total_pages || 0;
  if (j.status === "done") return `${j.filename}（已入库 ${c.success || 0}/${total} 页）`;
  if (j.status === "interrupted") return `${j.filename}（已中断，${c.pending || 0} 页待续）`;
  if (j.status === "failed") return `${j.filename}（处理失败）`;
  return `${j.filename}（导入中 ${c.success || 0}/${total} 页）`;
}

async function loadPdfScopeOptions() {
  let jobs = [];
  try { jobs = await api("/api/pdf"); } catch (_) { jobs = []; }
  const current = el.pdfSearchScope.value;
  el.pdfSearchScope.innerHTML = `<option value="">全部已导入 PDF</option>`;
  for (const j of jobs) {
    const opt = document.createElement("option");
    opt.value = j.pdf_id;
    opt.textContent = pdfScopeLabel(j);
    el.pdfSearchScope.appendChild(opt);
  }
  if ([...el.pdfSearchScope.options].some((o) => o.value === current))
    el.pdfSearchScope.value = current;
}

function showSearchResults() {
  el.pdfSearchResults.classList.remove("hidden");
}

function resetPdfSearchUI() {
  if (!el.pdfSearchResults) return;
  state.searchActive = false;
  state.searchQuery = "";
  el.pdfSearchResults.classList.add("hidden");
  el.pdfSearchResults.innerHTML = "";
  el.pdfSearchStatus.textContent = "";
  if (el.pdfQaResult) {
    resetPdfQaSession();
    el.pdfQaStatus.textContent = "";
  }
}

function highlightSnippet(snippet, query) {
  const html = esc(snippet || "");
  if (!query) return html;
  return html.replace(new RegExp(escapeRe(query), "gi"), (m) => `<mark>${m}</mark>`);
}

function renderSearchHits(hits, query) {
  el.pdfSearchResults.innerHTML = "";
  for (const h of hits) {
    const card = document.createElement("div");
    card.className = "search-hit";
    const page = h.page_number ? `第 ${h.page_number} 页` : `第 ${h.page_index + 1} 页`;
    card.innerHTML = `
      <div class="search-hit-head">
        <a class="search-hit-title" href="#doc/${encodeURIComponent(h.document_id)}">${esc(h.title || h.document_id)}</a>
        <span class="search-hit-page dim">${page} · 原页序 ${h.page_index + 1}</span>
      </div>
      <div class="search-hit-snippet">${highlightSnippet(h.snippet, query)}</div>
      <div class="search-hit-links">
        <a href="#doc/${encodeURIComponent(h.document_id)}">打开校对文档</a>
        <a href="${h.source_page_url}" target="_blank" rel="noopener">查看原 PDF 页</a>
      </div>`;
    el.pdfSearchResults.appendChild(card);
  }
}

async function runPdfSearch() {
  const q = (el.pdfSearchInput.value || "").trim();
  state.searchQuery = q;
  state.searchActive = !!q;
  if (!q) { resetPdfSearchUI(); return; }
  el.pdfSearchStatus.textContent = "检索中…";
  el.pdfSearchResults.innerHTML = "";
  const params = new URLSearchParams({ q });
  if (el.pdfSearchScope.value) params.set("pdf_id", el.pdfSearchScope.value);
  let r;
  try { r = await api(`/api/search/pdf?${params.toString()}`); }
  catch (e) { el.pdfSearchStatus.textContent = "搜索失败：" + e.message; return; }
  showSearchResults();
  el.pdfSearchStatus.textContent = r.total
    ? `命中 ${r.total} 条 · 检索范围 ${r.indexed_documents} 页`
    : (r.message || "没有匹配的内容。");
  renderSearchHits(r.hits || [], q);
}

/* ---------- PDF grounded Q&A (issue 11 + P1 multi-turn) ---------- */

function newPdfQaSessionId() {
  if (window.crypto && typeof crypto.randomUUID === "function")
    return "qa-" + crypto.randomUUID();
  return "qa-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

function currentQaScopeKey() {
  return el.pdfSearchScope ? (el.pdfSearchScope.value || "") : "";
}

function resetPdfQaSession(opts) {
  state.pdfQaSessionId = newPdfQaSessionId();
  state.pdfQaScopeKey = currentQaScopeKey();
  state.pdfQaHistory = [];
  if (el.pdfQaHistory) {
    el.pdfQaHistory.innerHTML = "";
    el.pdfQaHistory.classList.add("hidden");
  }
  if (el.pdfQaResult) {
    el.pdfQaResult.innerHTML = "";
    el.pdfQaResult.classList.add("hidden");
  }
  if (opts && opts.notice && el.pdfQaStatus) el.pdfQaStatus.textContent = opts.notice;
}

function historyCitationHtml(c) {
  const page = c.page_number ? `第 ${c.page_number} 页` : `第 ${c.page_index + 1} 页`;
  return `<li><span class="pdf-qa-prior">前文提到</span> `
    + `<a href="#doc/${encodeURIComponent(c.document_id)}">${esc(c.label)} ${esc(c.title || c.document_id)}</a>`
    + ` <span class="dim">${page} · 原页序 ${c.page_index + 1}</span>`
    + ` <a href="${c.source_page_url}" target="_blank" rel="noopener">查看原 PDF 页</a></li>`;
}

function renderPdfQaHistory() {
  if (!el.pdfQaHistory) return;
  const prior = state.pdfQaHistory.slice(0, -1);
  if (!prior.length) {
    el.pdfQaHistory.innerHTML = "";
    el.pdfQaHistory.classList.add("hidden");
    return;
  }
  el.pdfQaHistory.innerHTML = prior.map((turn, i) => {
    const r = turn.response || {};
    const answer = r.answer
      ? esc(r.answer).replace(/\n/g, "<br>")
      : `<span class="dim">${esc(r.message || r.status || "未作答")}</span>`;
    const cits = (r.citations && r.citations.length)
      ? `<ol class="pdf-qa-history-citations">${r.citations.map(historyCitationHtml).join("")}</ol>`
      : "";
    return `<div class="pdf-qa-turn">`
      + `<div class="pdf-qa-turn-q">第 ${i + 1} 轮 · ${esc(turn.question)}</div>`
      + `<div class="pdf-qa-turn-a">${answer}</div>${cits}</div>`;
  }).join("");
  el.pdfQaHistory.classList.remove("hidden");
}

function renderPdfAnswer(r) {
  const parts = [];
  if (r.answer) {
    parts.push(`<div class="pdf-qa-answer">${esc(r.answer).replace(/\n/g, "<br>")}</div>`);
  } else if (r.message) {
    parts.push(`<div class="pdf-qa-answer dim">${esc(r.message)}</div>`);
  }
  if (r.citations && r.citations.length) {
    const items = r.citations.map((c) => {
      const page = c.page_number ? `第 ${c.page_number} 页` : `第 ${c.page_index + 1} 页`;
      return `<li><a href="#doc/${encodeURIComponent(c.document_id)}">${esc(c.label)} ${esc(c.title || c.document_id)}</a>`
        + ` <span class="dim">${page} · 原页序 ${c.page_index + 1}</span>`
        + ` <a href="${c.source_page_url}" target="_blank" rel="noopener">查看原 PDF 页</a></li>`;
    }).join("");
    parts.push(`<div class="pdf-qa-citations"><div class="dim">引用来源</div><ol>${items}</ol></div>`);
  }
  const warn = [];
  if (r.untrusted_citations && r.untrusted_citations.length)
    warn.push(`模型给出的无效引用已忽略：${r.untrusted_citations.map((x) => esc(x)).join("、")}`);
  for (const w of (r.warnings || [])) warn.push(esc(w));
  if (warn.length) parts.push(`<div class="pdf-qa-warn">${warn.join("<br>")}</div>`);
  return parts.join("");
}

async function askPdf() {
  const q = (el.pdfQaInput.value || "").trim();
  if (!q) { el.pdfQaStatus.textContent = "请输入问题。"; return; }
  if (!state.pdfQaSessionId || state.pdfQaScopeKey !== currentQaScopeKey())
    resetPdfQaSession();
  el.pdfQaStatus.textContent = "检索并生成中…";
  el.pdfQaResult.classList.add("hidden");
  el.pdfQaResult.innerHTML = "";
  const payload = { question: q, session_id: state.pdfQaSessionId };
  if (el.pdfSearchScope.value) payload.pdf_id = el.pdfSearchScope.value;
  let r;
  try {
    r = await api("/api/pdf/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    // a scope conflict means the caller must start an explicit new session
    if (String(e.message || "").includes("新建会话")) resetPdfQaSession();
    el.pdfQaStatus.textContent = "提问失败：" + e.message;
    return;
  }
  const labels = {
    answered: r.grounded ? "已生成（含页级引用）" : "已生成（未引用来源）",
    insufficient_evidence: "证据不足",
    timeout: "生成超时",
    model_unavailable: "模型不可用",
  };
  const turn = (r.session && r.session.turn_index) || (state.pdfQaHistory.length + 1);
  el.pdfQaStatus.textContent = `第 ${turn} 轮 · ${labels[r.status] || r.status}`
    + ` · 检索 ${r.retrieved} 条`
    + (r.model ? ` · ${r.model}` : "");
  el.pdfQaResult.innerHTML = renderPdfAnswer(r);
  el.pdfQaResult.classList.remove("hidden");
  state.pdfQaHistory.push({ question: q, response: r });
  renderPdfQaHistory();
  el.pdfQaInput.value = "";
}

/* ---------- PDF upload / per-page job (issue 08/09) ---------- */

const PDF_STATUS_LABEL = {
  pending: "待处理", processing: "解析中", success: "成功",
  failed: "失败", blank: "空白页", duplicate: "重复页",
  interrupted: "已中断",
};

function acceptPdf(file) {
  if (!file) return;
  if (!/\.pdf$/i.test(file.name)) {
    el.uploadHint.textContent = "不支持的文件类型：请上传 PDF。"; return;
  }
  if (file.size > 50 * 1024 * 1024) {
    el.uploadHint.textContent = `文件 ${(file.size / 1048576).toFixed(1)}MB 超过 50MB 上限。`;
    return;
  }
  el.uploadHint.textContent = "";
  startPdfUpload(file);
}

async function startPdfUpload(file) {
  if (state.busy) return;
  state.busy = true; setBusy(true);
  showWorking("正在上传 PDF…", file.name);
  try {
    const r = await api("/api/pdf", {
      method: "POST",
      body: (() => { const f = new FormData(); f.append("file", file); return f; })(),
    });
    pollPdf(r.pdf_id);
  } catch (e) {
    state.busy = false; setBusy(false);
    el.uploadHint.textContent = e.message;
    go("#upload");
  }
}

function pollPdf(pdfId) {
  state.pdfId = pdfId;
  hideAll();
  el.pdfZone.classList.remove("hidden");
  el.pdfList.innerHTML = "";
  clearInterval(state.pollTimer);
  const tick = async () => {
      let job;
      try { job = await api(`/api/pdf/${pdfId}`); }
      catch (e) { clearInterval(state.pollTimer); showToast("查询 PDF 任务失败：" + e.message, "err"); go("#library"); return; }
      el.pdfFilename.textContent = job.filename || "";
      renderPdfSummary(job);
      renderPdfPages(job);
      const running = job.status === "queued" || job.status === "processing";
      // issue 09: show retry only when there is unfinished/retryable work
      const canRetry = job.retryable || job.exhausted || job.status === "interrupted";
      el.pdfRetry.classList.toggle("hidden", !canRetry);
      el.pdfRetry.disabled = !!job.running;
      if (!running) {
        clearInterval(state.pollTimer);
        state.busy = false; setBusy(false);
        if (job.status !== "done") showToast(job.error || "PDF 处理未完成。", "err");
      }
  };
  tick();
  state.pollTimer = setInterval(tick, POLL_MS);
}

function pdfCountsText(job) {
  const c = job.counts || {};
  return `共 ${job.total_pages} 页 · ${c.success || 0} 成功 / ${c.failed || 0} 失败 / ${c.blank || 0} 空白 / ${c.duplicate || 0} 重复`;
}

function renderPdfSummary(job) {
  const running = job.status === "queued" || job.status === "processing";
  if (running) {
    const done = (job.counts && (job.counts.success || 0)) || 0;
    el.pdfSummary.textContent = `正在逐页解析… ${done}/${job.total_pages} 页已完成`;
    return;
  }
  let text = pdfCountsText(job);
  const retryable = (job.pages || []).filter((p) => p.retryable).length;
  if (job.status === "interrupted") {
    text += ` · 已中断，${retryable} 页可重试`;
  } else if (job.exhausted) {
    text += ` · 有页面已达 ${job.max_page_attempts} 次尝试上限，已停止重试`;
  } else if (retryable) {
    text += ` · ${retryable} 页可重试`;
  }
  el.pdfSummary.textContent = text;
}

function renderPdfPages(job) {
  el.pdfList.innerHTML = "";
  for (const p of (job.pages || [])) {
    const row = document.createElement("div");
    row.className = "pdf-row";
    const badge = `<span class="pdf-badge st-${p.status}">${PDF_STATUS_LABEL[p.status] || p.status}</span>`;
    const link = p.document_id
      ? `<a href="#doc/${encodeURIComponent(p.document_id)}">第 ${p.page_index + 1} 页</a>`
      : `<span>第 ${p.page_index + 1} 页</span>`;
    let note = "";
    if (p.status === "duplicate") {
      note = `（与第 ${(p.merged_into || 0) + 1} 页重复）`;
    } else if (p.status === "failed") {
      const tries = p.attempts ? `已尝试 ${p.attempts}/${job.max_page_attempts} 次` : "";
      const err = p.error ? esc(p.error) : "";
      const detail = [tries, err].filter(Boolean).join("：");
      note = detail ? `（${detail}）` : "";
    } else if (p.error) {
      note = `（${esc(p.error)}）`;
    }
    row.innerHTML = `<span class="pdf-page">${link}</span>${badge}<span class="dim">${note}</span>`;
    el.pdfList.appendChild(row);
  }
}

async function retryPdf(pdfId) {
  clearInterval(state.pollTimer);
  try {
    const r = await api(`/api/pdf/${pdfId}/retry`, { method: "POST" });
    if (!r.triggered) showToast(r.message || "没有可重试的页面。", "");
  } catch (e) {
    showToast("重试失败：" + e.message, "err");
  }
  pollPdf(pdfId);
}

/* ---------- view ---------- */

function renderPdfSearch() {
  el.pdfSearchZone.classList.remove("hidden");
  resetPdfSearchUI();
  loadPdfScopeOptions();
}

el.pdfSearchForm.addEventListener("submit", (e) => {
  e.preventDefault();
  runPdfSearch();
});
el.pdfSearchClear.addEventListener("click", () => {
  el.pdfSearchInput.value = "";
  el.pdfSearchScope.value = "";
  resetPdfSearchUI();
});
el.pdfSearchScope.addEventListener("change", () => {
  // switching retrieval scope is a new topic: start an explicit new session
  if (el.pdfQaResult) resetPdfQaSession({ notice: "检索范围已更改，已开启新会话。" });
  if (state.searchActive || (el.pdfSearchInput.value || "").trim()) runPdfSearch();
});
el.pdfQaForm.addEventListener("submit", (e) => { e.preventDefault(); askPdf(); });
if (el.pdfQaNew) {
  el.pdfQaNew.addEventListener("click", () => {
    resetPdfQaSession({ notice: "已开启新会话（上下文已清空）。" });
  });
}

el.pickPdf.onclick = () => el.pdfInput.click();
el.pdfInput.addEventListener("change", (e) => acceptPdf(e.target.files[0]));
el.pdfRetry.addEventListener("click", () => {
  if (state.pdfId) retryPdf(state.pdfId);
});

registerView("pdf-search", renderPdfSearch);
