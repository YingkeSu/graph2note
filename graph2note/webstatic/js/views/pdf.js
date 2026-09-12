/* graph2note — PDF per-page upload status (issue 08/09) + PDF content search
   (issue 10).

   P2 moved the grounded Q&A out of this module into the first-class `#ask`
   conversation view (`views/ask.js`).  What remains here is the per-page upload
   job view plus the keyword-search toolbar, which the ask view mounts as an
   auxiliary tool (P3 owns the unified-search frontend).  The search behaviour
   itself is unchanged; `loadPdfScopeOptions(el)` is exported for the ask view. */
"use strict";

import { el, state, hideAll, setBusy } from "../state.js";
import { api } from "../api.js";
import { esc, escapeRe, POLL_MS } from "../utils.js";
import { go } from "../router.js";
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

/* Populate a scope `<select>` with the imported PDFs (current value kept). */
export async function loadPdfScopeOptions(selectEl) {
  const select = selectEl || el.pdfSearchScope;
  if (!select) return;
  let jobs = [];
  try { jobs = await api("/api/pdf"); } catch (_) { jobs = []; }
  const current = select.value;
  select.innerHTML = `<option value="">全部已导入 PDF</option>`;
  for (const j of jobs) {
    const opt = document.createElement("option");
    opt.value = j.pdf_id;
    opt.textContent = pdfScopeLabel(j);
    select.appendChild(opt);
  }
  if ([...select.options].some((o) => o.value === current))
    select.value = current;
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

/* ---------- wiring ---------- */

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
  if (state.searchActive || (el.pdfSearchInput.value || "").trim()) runPdfSearch();
});

el.pickPdf.onclick = () => el.pdfInput.click();
el.pdfInput.addEventListener("change", (e) => acceptPdf(e.target.files[0]));
el.pdfRetry.addEventListener("click", () => {
  if (state.pdfId) retryPdf(state.pdfId);
});
