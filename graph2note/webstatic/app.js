/* graph2note — local document library + three-pane review/edit.
   Views routed by location.hash: #library (home), #timeline/day|week,
   #graph, #dashboard, #inbox, #upload, #doc/<id>. */
"use strict";

const $ = (s) => document.querySelector(s);
const POLL_MS = 1200;
const SAVE_MS = 800;

const state = {
  route: "library",
  docId: null,
  doc: null,        // last loaded document record
  busy: false,
  pollTimer: null,
  jobId: null,
  pdfId: null,
  searchActive: false,
  searchQuery: "",
  libraryCollection: null,
  libraryFilter: "all",
  libraryTag: null,
  libraryTopic: null,
  timelineGroup: "day",
  llmSettings: null,
};

const el = {
  libraryZone: $("#library-zone"),
  inboxZone: $("#inbox-zone"),
  inboxEmpty: $("#inbox-empty"),
  inboxList: $("#inbox-list"),
  settingsZone: $("#settings-zone"),
  llmProviderList: $("#llm-provider-list"),
  llmChannelList: $("#llm-channel-list"),
  llmHealthList: $("#llm-health-list"),
  llmHealthButton: $("#llm-health-button"),
  llmSaveButton: $("#llm-save-button"),
  timelineZone: $("#timeline-zone"),
  graphZone: $("#graph-zone"),
  graphEmpty: $("#graph-empty"),
  graphScroll: $("#graph-scroll"),
  graphCanvas: $("#graph-canvas"),
  dashboardZone: $("#dashboard-zone"),
  dashboardEmpty: $("#dashboard-empty"),
  dashboardContent: $("#dashboard-content"),
  dashboardQualityLabel: $("#dashboard-quality-label"),
  dashboardPeriods: $("#dashboard-periods"),
  dashboardQuality: $("#dashboard-quality"),
  dashboardTrend: $("#dashboard-trend"),
  dashboardCategories: $("#dashboard-categories"),
  dashboardTags: $("#dashboard-tags"),
  dashboardModels: $("#dashboard-models"),
  dashboardDay: $("#dashboard-day"),
  dashboardMonth: $("#dashboard-month"),
  timelineGroups: $("#timeline-groups"),
  timelineEmpty: $("#timeline-empty"),
  timelineUndated: $("#timeline-undated"),
  timelineUndatedCount: $("#timeline-undated-count"),
  timelineUndatedItems: $("#timeline-undated-items"),
  timelineGroup: $("#timeline-group"),
  libraryGrid: $("#library-grid"),
  libraryEmpty: $("#library-empty"),
  libraryCount: $("#library-count"),
  libraryFilterLabel: $("#library-filter-label"),
  collectionTree: $("#collection-tree"),
  collectionCreateForm: $("#collection-create-form"),
  collectionCreateInput: $("#collection-create-input"),
  documentCollectionForm: $("#document-collection-form"),
  documentCollectionSelect: $("#document-collection-select"),
  documentCollectionList: $("#document-collection-list"),
  tagList: $("#tag-list"),
  tagCreateForm: $("#tag-create-form"),
  tagCreateInput: $("#tag-create-input"),
  uploadZone: $("#upload-zone"),
  uploadCard: $("#upload-card"),
  fileInput: $("#file-input"),
  pickFile: $("#pick-file"),
  uploadHint: $("#upload-hint"),
  workingZone: $("#working-zone"),
  workingText: $("#working-text"),
  workingDetail: $("#working-detail"),
  workZone: $("#work-zone"),
  originalImg: $("#original-img"),
  mdEditor: $("#md-editor"),
  preview: $("#preview"),
  statusText: $("#status-text"),
  warnings: $("#warnings"),
  versionInfo: $("#version-info"),
  documentTagForm: $("#document-tag-form"),
  documentTagInput: $("#document-tag-input"),
  documentTagList: $("#document-tag-list"),
  metadataDocumentTime: $("#metadata-document-time"),
  metadataNeedsOrganization: $("#metadata-needs-organization"),
  metadataCaptureTime: $("#metadata-capture-time"),
  metadataImportTime: $("#metadata-import-time"),
  metadataModifiedTime: $("#metadata-modified-time"),
  metadataEvidence: $("#metadata-evidence"),
  metadataSave: $("#metadata-save"),
  saveIndicator: $("#save-indicator"),
  toast: $("#toast"),
  btnReparse: $("#btn-reparse"),
  btnCopy: $("#btn-copy"),
  btnDownload: $("#btn-download"),
  btnDelete: $("#btn-delete"),
  btnRepic: $("#btn-repic"),
  navLibrary: $("#nav-library"),
  navInbox: $("#nav-inbox"),
  navTimeline: $("#nav-timeline"),
  navGraph: $("#nav-graph"),
  navDashboard: $("#nav-dashboard"),
  navSettings: $("#nav-settings"),
  navVaultExport: $("#nav-vault-export"),
  navUpload: $("#nav-upload"),
  modelLabel: $("#model-label"),
  vaultExportZone: $("#vault-export-zone"),
  vaultExportForm: $("#vault-export-form"),
  vaultExportDir: $("#vault-export-dir"),
  btnVaultExport: $("#btn-vault-export"),
  vaultExportStatus: $("#vault-export-status"),
  pickPdf: $("#pick-pdf"),
  pdfInput: $("#pdf-input"),
  pdfZone: $("#pdf-zone"),
  pdfList: $("#pdf-list"),
  pdfFilename: $("#pdf-filename"),
  pdfSummary: $("#pdf-summary"),
  pdfRetry: $("#pdf-retry"),
  pdfSearchForm: $("#pdf-search-form"),
  pdfSearchInput: $("#pdf-search-input"),
  pdfSearchScope: $("#pdf-search-scope"),
  pdfSearchStatus: $("#pdf-search-status"),
  pdfSearchResults: $("#pdf-search-results"),
  pdfSearchClear: $("#pdf-search-clear"),
  pdfQaForm: $("#pdf-qa-form"),
  pdfQaInput: $("#pdf-qa-input"),
  pdfQaStatus: $("#pdf-qa-status"),
  pdfQaResult: $("#pdf-qa-result"),
};

/* ---------- helpers ---------- */

function showToast(msg, kind = "") {
  el.toast.textContent = msg;
  el.toast.className = "toast " + kind;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.toast.classList.add("hidden"), kind === "err" ? 6000 : 3000);
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function api(route, opts = {}) {
  const res = await fetch(route, opts);
  const ct = res.headers.get("content-type") || "";
  let body;
  try {
    body = ct.includes("json") ? await res.json() : await res.blob();
  } catch (_) {
    body = {};
  }
  if (!res.ok) {
    const msg = (body && body.detail) || res.statusText;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return body;
}

function setBusy(b) {
  state.busy = b;
  [el.btnReparse, el.btnCopy, el.btnDownload, el.btnDelete, el.navUpload]
    .forEach((n) => { if (n) n.disabled = b; });
}

/* ---------- routing ---------- */

function go(route) {
  if (location.hash === route) { render(); }
  else { location.hash = route; }
}

function parseHash() {
  const h = (location.hash || "#library").replace(/^#\/?/, "");
  const parts = h.split("/");
  if (parts[0] === "doc" && parts[1]) return { name: "doc", id: decodeURIComponent(parts[1]) };
  if (parts[0] === "inbox") return { name: "inbox" };
  if (parts[0] === "settings") return { name: "settings" };
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
  if (parts[0] === "upload") return { name: "upload" };
  if (parts[0] === "vault-export") return { name: "vault-export" };
  return { name: "library" };
}

function render() {
  const r = parseHash();
  state.route = r.name;
  hideAll();
  if (r.name === "upload") { renderUpload(); }
  else if (r.name === "doc") { state.docId = r.id; renderDocument(r.id); }
  else if (r.name === "inbox") { renderInbox(); }
  else if (r.name === "settings") { renderLlmSettings(); }
  else if (r.name === "timeline") { state.timelineGroup = r.group; renderTimeline(r.group); }
  else if (r.name === "graph") { renderGraph(); }
  else if (r.name === "dashboard") { renderDashboard(); }
  else if (r.name === "vault-export") { renderVaultExport(); }
  else {
    state.libraryTag = r.tag || null;
    state.libraryTopic = r.topic || null;
    if (r.collection) {
      state.libraryCollection = r.collection;
      state.libraryTag = null;
      state.libraryTopic = null;
      state.libraryFilter = "all";
    }
    if (r.tag || r.topic) {
      state.libraryCollection = null;
      state.libraryFilter = "all";
    }
    renderLibrary();
  }
}

function hideAll() {
  [el.libraryZone, el.inboxZone, el.settingsZone, el.timelineZone, el.graphZone, el.dashboardZone, el.uploadZone, el.workingZone, el.workZone, el.vaultExportZone, el.pdfZone]
    .forEach((n) => n.classList.add("hidden"));
}

window.addEventListener("hashchange", render);

/* ---------- library ---------- */

async function renderLibrary() {
  el.libraryZone.classList.remove("hidden");
  resetPdfSearchUI();
  el.libraryGrid.innerHTML = "";
  let docs = [];
  const params = new URLSearchParams();
  if (state.libraryCollection) params.set("collection_id", state.libraryCollection);
  if (state.libraryTag) params.set("tag", state.libraryTag);
  if (state.libraryTopic) params.set("topic", state.libraryTopic);
  const query = params.toString() ? `?${params.toString()}` : "";
  try { docs = await api(`/api/documents${query}`); }
  catch (e) { showToast("加载文档库失败：" + e.message, "err"); }
  docs = filterLibraryDocuments(docs);
  el.libraryCount.textContent = docs.length ? `共 ${docs.length} 份` : "";
  if (el.libraryFilterLabel) {
    el.libraryFilterLabel.textContent = state.libraryTopic
      ? `主题：${state.libraryTopic}`
      : state.libraryTag ? `标签：#${state.libraryTag}` : "";
  }
  el.libraryEmpty.classList.toggle("hidden", docs.length > 0);
  for (const d of docs) {
    const card = document.createElement("div");
    card.className = "doc-card";
    card.dataset.id = d.document_id;
    card.innerHTML = `
      <div class="thumb"><img loading="lazy" alt="" data-src="/api/documents/${encodeURIComponent(d.document_id)}/preprocessed"></div>
      <div class="doc-meta">
        <div class="doc-title">${esc(d.title)}</div>
        <div class="doc-time dim">更新 ${esc((d.updated_at || "").replace("T", " "))}${d.version_count > 1 ? ` · ${d.version_count} 版` : ""}</div>
      </div>`;
    card.addEventListener("click", () => go(`#doc/${encodeURIComponent(d.document_id)}`));
    el.libraryGrid.appendChild(card);
  }
  await renderCollectionNavigation();
  await renderTagVocabulary();
  await loadPdfScopeOptions();
  // lazy-load thumbnails
  requestAnimationFrame(() => {
    el.libraryGrid.querySelectorAll("img[data-src]").forEach((img) => {
      img.src = img.dataset.src;
      img.removeAttribute("data-src");
      img.onerror = () => { img.remove(); };
    });
  });
}

function filterLibraryDocuments(docs) {
  if (state.libraryFilter === "recent") return docs.slice(0, 12);
  if (state.libraryFilter === "all") return docs;
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  const start = new Date(now);
  start.setDate(start.getDate() - (state.libraryFilter === "week" ? 6 : 0));
  const lower = start.toISOString().slice(0, 10);
  return docs.filter((doc) => {
    const value = doc.metadata && doc.metadata.import_time && doc.metadata.import_time.value;
    const day = value ? String(value).slice(0, 10) : "";
    return state.libraryFilter === "today" ? day === today : day >= lower && day <= today;
  });
}

/* ---------- PDF content search (issue 10) ---------- */

function escapeRe(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

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
  el.libraryGrid.classList.add("hidden");
  el.libraryEmpty.classList.add("hidden");
}

function resetPdfSearchUI() {
  if (!el.pdfSearchResults) return;
  state.searchActive = false;
  state.searchQuery = "";
  el.pdfSearchResults.classList.add("hidden");
  el.pdfSearchResults.innerHTML = "";
  el.pdfSearchStatus.textContent = "";
  el.libraryGrid.classList.remove("hidden");
  if (el.pdfQaResult) {
    el.pdfQaResult.classList.add("hidden");
    el.pdfQaResult.innerHTML = "";
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

/* ---------- PDF grounded Q&A (issue 11) ---------- */

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
  el.pdfQaStatus.textContent = "检索并生成中…";
  el.pdfQaResult.classList.add("hidden");
  el.pdfQaResult.innerHTML = "";
  const payload = { question: q };
  if (el.pdfSearchScope.value) payload.pdf_id = el.pdfSearchScope.value;
  let r;
  try {
    r = await api("/api/pdf/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    el.pdfQaStatus.textContent = "提问失败：" + e.message;
    return;
  }
  const labels = {
    answered: r.grounded ? "已生成（含页级引用）" : "已生成（未引用来源）",
    insufficient_evidence: "证据不足",
    timeout: "生成超时",
    model_unavailable: "模型不可用",
  };
  el.pdfQaStatus.textContent = `${labels[r.status] || r.status} · 检索 ${r.retrieved} 条`
    + (r.model ? ` · ${r.model}` : "");
  el.pdfQaResult.innerHTML = renderPdfAnswer(r);
  el.pdfQaResult.classList.remove("hidden");
}

el.pdfQaForm.addEventListener("submit", (e) => { e.preventDefault(); askPdf(); });

/* ---------- Inbox (read-only projection) ---------- */

function inboxItemHtml(item) {
  const reasons = (item.inbox_reason_labels || []).map((reason) =>
    `<span class="inbox-reason">${esc(reason)}</span>`).join("");
  const topics = (item.topics || []).map((topic) =>
    `<span class="timeline-topic">${esc(topic)}</span>`).join("");
  const tags = (item.tags || []).map((tag) =>
    `<span class="document-tag">#${esc(tag)}</span>`).join("");
  const effective = item.effective_time && item.effective_time.value
    ? displayTime(item.effective_time.value) : "无有效日期";
  return `<button class="inbox-item" type="button" data-route="${esc(`#doc/${encodeURIComponent(item.document_id)}`)}">
    <span class="inbox-item-main">
      <span class="inbox-item-title">${esc(item.title)}</span>
      <span class="inbox-item-meta">${esc(effective)}${topics}${tags}</span>
    </span>
    <span class="inbox-reasons">${reasons}</span>
    <span class="inbox-item-arrow" aria-hidden="true">›</span>
  </button>`;
}

async function renderInbox() {
  el.inboxZone.classList.remove("hidden");
  el.inboxList.innerHTML = "";
  el.inboxEmpty.classList.add("hidden");
  try {
    const items = await api("/api/inbox");
    if (!items.length) {
      el.inboxEmpty.classList.remove("hidden");
      return;
    }
    el.inboxList.innerHTML = items.map(inboxItemHtml).join("");
    el.inboxList.querySelectorAll("button.inbox-item[data-route]").forEach((button) => {
      button.addEventListener("click", () => go(button.dataset.route));
    });
  } catch (e) {
    el.inboxEmpty.classList.remove("hidden");
    el.inboxEmpty.querySelector("p").textContent = "Inbox 加载失败。";
    showToast("加载 Inbox 失败：" + e.message, "err");
  }
}

/* ---------- LLM provider/model settings (read/write local config) ---------- */

function llmStatusText(status) {
  return {
    available: "可用",
    missing_credentials: "未配置凭证",
    auth_failed: "认证失败",
    request_failed: "请求失败",
  }[status] || "未检测";
}

function llmStatusClass(status) {
  return status ? `llm-status ${esc(status)}` : "llm-status";
}

function updateLlmModelOptions(row, selected) {
  const providerId = row.querySelector(".llm-provider").value;
  const purpose = row.dataset.purpose;
  const provider = (state.llmSettings.providers || []).find((item) => item.id === providerId);
  const models = provider && provider.capabilities[purpose]
    ? provider.capabilities[purpose].models || [] : [];
  const select = row.querySelector(".llm-model");
  select.innerHTML = models.map((model) =>
    `<option value="${esc(model)}">${esc(model)}</option>`).join("");
  if (models.includes(selected)) select.value = selected;
}

function renderLlmChannels(snapshot) {
  const providers = snapshot.providers || [];
  el.llmProviderList.innerHTML = providers.map((provider) => `
    <div class="llm-provider-card">
      <span>${esc(provider.name)}</span>
      <span class="dim">${provider.credential_configured ? "凭证已配置" : "未配置凭证"}</span>
    </div>`).join("");
  el.llmChannelList.innerHTML = (snapshot.purposes || []).map((purpose) => {
    const current = snapshot.channels[purpose];
    const label = (snapshot.purpose_labels || {})[purpose] || purpose;
    const options = providers.map((provider) =>
      `<option value="${esc(provider.id)}"${provider.id === current.provider ? " selected" : ""}>${esc(provider.name)}</option>`
    ).join("");
    return `<div class="llm-channel-row" data-purpose="${esc(purpose)}">
      <div class="llm-channel-label"><strong>${esc(label)}</strong><span class="dim">${esc(purpose)}</span></div>
      <select class="llm-provider" aria-label="${esc(label)}供应商">${options}</select>
      <select class="llm-model" aria-label="${esc(label)}模型"></select>
      <span class="llm-status">未检测</span>
    </div>`;
  }).join("");
  el.llmChannelList.querySelectorAll(".llm-channel-row").forEach((row) => {
    const current = snapshot.channels[row.dataset.purpose];
    updateLlmModelOptions(row, current && current.model);
    row.querySelector(".llm-provider").addEventListener("change", () => updateLlmModelOptions(row));
  });
}

function renderLlmHealth(payload) {
  const statuses = payload.statuses || {};
  el.llmHealthList.innerHTML = (state.llmSettings.purposes || []).map((purpose) => {
    const item = statuses[purpose] || {};
    const label = state.llmSettings.purpose_labels[purpose] || purpose;
    const detail = item.detail ? ` · ${esc(item.detail)}` : "";
    const status = item.status || "not_checked";
    const row = Array.from(el.llmChannelList.querySelectorAll(".llm-channel-row"))
      .find((candidate) => candidate.dataset.purpose === purpose);
    if (row) {
      const badge = row.querySelector(".llm-status");
      badge.className = llmStatusClass(status);
      badge.textContent = llmStatusText(status);
    }
    return `<div class="llm-health-item"><strong>${esc(label)}</strong><span class="${llmStatusClass(status)}">${llmStatusText(status)}</span><span class="dim">${esc(item.provider || "")}/${esc(item.model || "")}${detail}</span></div>`;
  }).join("");
}

async function renderLlmSettings() {
  el.settingsZone.classList.remove("hidden");
  el.llmChannelList.innerHTML = "<p class=\"dim\">加载配置中…</p>";
  try {
    state.llmSettings = await api("/api/llm/settings");
    renderLlmChannels(state.llmSettings);
    el.llmHealthList.innerHTML = "<p class=\"dim\">尚未检测通道可用性。</p>";
  } catch (e) {
    el.llmChannelList.innerHTML = `<p class="dim">加载失败：${esc(e.message)}</p>`;
    showToast("加载 LLM 设置失败：" + e.message, "err");
  }
}

async function saveLlmSettings() {
  if (!state.llmSettings) return;
  const channels = {};
  el.llmChannelList.querySelectorAll(".llm-channel-row").forEach((row) => {
    channels[row.dataset.purpose] = {
      provider: row.querySelector(".llm-provider").value,
      model: row.querySelector(".llm-model").value,
    };
  });
  try {
    state.llmSettings = await api("/api/llm/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channels }),
    });
    renderLlmChannels(state.llmSettings);
    showToast("LLM 配置已保存，下一次任务生效", "ok");
  } catch (e) { showToast("保存 LLM 配置失败：" + e.message, "err"); }
}

async function checkLlmHealth() {
  el.llmHealthButton.disabled = true;
  el.llmHealthButton.textContent = "检测中…";
  try {
    renderLlmHealth(await api("/api/llm/health", { method: "POST" }));
  } catch (e) { showToast("检测 LLM 通道失败：" + e.message, "err"); }
  el.llmHealthButton.disabled = false;
  el.llmHealthButton.textContent = "检测可用性";
}

/* ---------- Obsidian vault export (one-way) ---------- */

let vaultPollTimer = null;
let vaultExportTaskId = null;

const VAULT_REPORT_LABELS = {
  added: "新增", updated: "更新", deleted: "删除", unchanged: "无变化",
  conflicts: "冲突", kept_user: "保留的用户文件", user_files: "用户文件",
};

function vaultCounts(report) {
  if (!report) return "";
  return Object.keys(VAULT_REPORT_LABELS).filter((key) =>
    Array.isArray(report[key]) && report[key].length
  ).map((key) => `${VAULT_REPORT_LABELS[key]} ${report[key].length}`).join(" · ");
}

function showVaultStatus(text, detail) {
  el.vaultExportStatus.innerHTML = "";
  const line = document.createElement("div");
  line.textContent = text;
  el.vaultExportStatus.appendChild(line);
  if (detail) {
    const d = document.createElement("div");
    d.className = "dim";
    d.textContent = detail;
    el.vaultExportStatus.appendChild(d);
  }
}

function vaultFileList(title, items) {
  if (!items || !items.length) return "";
  const lis = items.map((item) =>
    `<li>${esc(typeof item === "string" ? item : (item.managed || item.backup || ""))}</li>`).join("");
  return `<details class="vault-files"><summary>${esc(title)}（${items.length}）</summary><ul>${lis}</ul></details>`;
}

function vaultConflictsHtml(conflicts) {
  if (!conflicts || !conflicts.length) return "";
  const rows = conflicts.map((c) => `
    <li>
      <div>受管输出：<code>${esc(c.managed)}</code></div>
      <div class="dim">您的版本已保留为备份：<code>${esc(c.backup)}</code></div>
    </li>`).join("");
  return `<div class="vault-conflicts"><strong>检测到冲突：您手工修改过的文件未被覆盖，已保留为备份并同时生成系统版本（未自动合并）。请在 Obsidian 中核对两份内容。</strong><ul>${rows}</ul></div>`;
}

function renderVaultResult(st) {
  el.vaultExportStatus.classList.remove("ok", "err");
  el.vaultExportStatus.innerHTML = "";
  if (st.status === "done") {
    const r = st.report || {};
    el.vaultExportStatus.classList.add("ok");
    const head = document.createElement("div");
    head.textContent = `导出完成：${st.exported_documents} 份文档 → ${st.vault_root}`;
    el.vaultExportStatus.appendChild(head);
    const meta = document.createElement("div");
    meta.className = "dim";
    meta.textContent = (st.task_id ? `任务 ${st.task_id} · ` : "") + (vaultCounts(r) || "无变化");
    el.vaultExportStatus.appendChild(meta);
    el.vaultExportStatus.insertAdjacentHTML("beforeend",
      vaultConflictsHtml(r.conflicts) +
      vaultFileList("新增文件", r.added) +
      vaultFileList("更新文件", r.updated) +
      vaultFileList("删除文件", r.deleted) +
      vaultFileList("无变化文件", r.unchanged) +
      vaultFileList("保留的用户文件", r.kept_user) +
      vaultFileList("Vault 中的用户文件", r.user_files));
    showToast("已导出 Obsidian Vault", "ok");
  } else if (st.status === "failed") {
    el.vaultExportStatus.classList.add("err");
    const head = document.createElement("div");
    head.textContent = st.partial ? "导出失败（部分文件已写入，请核对 Vault）" : "导出失败";
    el.vaultExportStatus.appendChild(head);
    const err = document.createElement("div");
    err.className = "dim";
    err.textContent = st.error || "未知错误";
    el.vaultExportStatus.appendChild(err);
    showToast("导出失败：" + (st.error || ""), "err");
  }
}

function scheduleVaultPoll() {
  clearInterval(vaultPollTimer);
  const myTask = vaultExportTaskId;
  vaultPollTimer = setInterval(async () => {
    let st;
    try { st = await api("/api/vault/export"); }
    catch (e) { clearInterval(vaultPollTimer); return; }
    if (st.status === "running") return;
    if (myTask && st.task_id && st.task_id !== myTask) return;  // don't mix reports
    clearInterval(vaultPollTimer);
    renderVaultResult(st);
  }, POLL_MS);
}

async function renderVaultExport() {
  el.vaultExportZone.classList.remove("hidden");
  try {
    const st = await api("/api/vault/export");
    if (st && st.status === "running") {
      vaultExportTaskId = st.task_id || null;
      showVaultStatus("导出进行中…", st.target_dir || "");
      scheduleVaultPoll();
    } else if (st && (st.status === "done" || st.status === "failed")) {
      renderVaultResult(st);
    }
  } catch (e) { /* idle state is fine */ }
}

async function startVaultExport() {
  const dir = el.vaultExportDir.value.trim();
  if (!dir) { showToast("请填写目标目录路径", "err"); return; }
  el.btnVaultExport.disabled = true;
  showVaultStatus("正在导出…", dir);
  try {
    const r = await api("/api/vault/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_dir: dir }),
    });
    if (r.status === "empty") {
      showVaultStatus("文档库为空，没有可导出的文档。", "");
    } else {
      vaultExportTaskId = r.task_id || null;
      scheduleVaultPoll();
    }
  } catch (e) {
    el.vaultExportStatus.classList.add("err");
    showVaultStatus("导出失败", e.message);
  } finally {
    el.btnVaultExport.disabled = false;
  }
}

/* ---------- timeline (read-only view model) ---------- */

function timelineItemHtml(item) {
  const effective = item.effective_time || {};
  const topics = (item.topics || []).map((topic) => `<span class="timeline-topic">${esc(topic)}</span>`).join("");
  const collections = (item.collections || []).map((collection) => `<span class="timeline-collection">${esc(collection)}</span>`).join("");
  return `<button class="timeline-item" type="button" data-route="${esc(item.route)}">
    <span class="timeline-item-date">${esc(item.date || "无日期")}</span>
    <span class="timeline-item-main">
      <span class="timeline-item-title">${esc(item.title)}</span>
      <span class="timeline-item-meta">${esc(effective.source || "无有效时间")}${topics}${collections}</span>
    </span>
    <span class="timeline-item-arrow" aria-hidden="true">›</span>
  </button>`;
}

function timelineGroupHtml(group) {
  const aggregates = (group.topic_aggregates || []).map((item) =>
    `<span class="timeline-summary-chip">${esc(item.topic)} · ${item.count}</span>`).join("");
  const runs = (group.adjacent_topic_runs || []).filter((run) => run.count > 1).map((run) =>
    `<span class="timeline-run-chip">${esc(run.topic)} 连续 ${run.count} 份</span>`).join("");
  return `<section class="timeline-group">
    <div class="timeline-group-head">
      <div>
        <h3>${esc(group.label)}</h3>
        <span class="dim">${group.count} 份 · ${esc(group.start_date)}${group.end_date !== group.start_date ? ` 至 ${esc(group.end_date)}` : ""}</span>
      </div>
      <div class="timeline-summary">${aggregates || `<span class="dim">暂无主题</span>`}</div>
    </div>
    ${runs ? `<div class="timeline-runs"><span class="dim">相邻主题</span>${runs}</div>` : ""}
    <div class="timeline-items">${group.items.map(timelineItemHtml).join("")}</div>
  </section>`;
}

function wireTimelineLinks(root) {
  root.querySelectorAll("button.timeline-item[data-route]").forEach((button) => {
    button.addEventListener("click", () => go(button.dataset.route));
  });
}

async function renderTimeline(groupBy) {
  el.timelineZone.classList.remove("hidden");
  el.timelineGroup.value = groupBy;
  el.timelineGroups.innerHTML = "";
  el.timelineUndatedItems.innerHTML = "";
  el.timelineUndated.classList.add("hidden");
  el.timelineEmpty.classList.add("hidden");
  try {
    const timeline = await api(`/api/timeline?group_by=${encodeURIComponent(groupBy)}`);
    const total = Number(timeline.total || 0);
    if (!total) {
      el.timelineEmpty.classList.remove("hidden");
    } else {
      el.timelineGroups.innerHTML = (timeline.groups || []).map(timelineGroupHtml).join("");
      wireTimelineLinks(el.timelineGroups);
    }
    const undated = timeline.undated || [];
    if (undated.length) {
      el.timelineUndated.classList.remove("hidden");
      el.timelineUndatedCount.textContent = `${undated.length} 份`;
      el.timelineUndatedItems.innerHTML = undated.map(timelineItemHtml).join("");
      wireTimelineLinks(el.timelineUndatedItems);
    }
  } catch (e) {
    el.timelineEmpty.classList.remove("hidden");
    el.timelineEmpty.querySelector("p").textContent = "时间轴加载失败。";
    showToast("加载时间轴失败：" + e.message, "err");
  }
}

/* ---------- graph (read-only, provenance-aware navigation) ---------- */

const GRAPH_EDGE_COLORS = { topic: "#4f7fe8", tag: "#c07a1a", manual: "#16836d" };
const GRAPH_KIND_LABELS = { document: "文档", topic: "主题", tag: "标签", collection: "集合" };

function graphLayout(nodes) {
  const width = 1000;
  const columns = { document: 150, topic: 390, tag: 630, collection: 870 };
  const groups = {};
  for (const node of nodes) (groups[node.kind] ||= []).push(node);
  const maxCount = Math.max(1, ...Object.values(groups).map((items) => items.length));
  const height = Math.max(430, maxCount * 76 + 80);
  const positions = {};
  for (const [kind, items] of Object.entries(groups)) {
    const step = height / (items.length + 1);
    items.forEach((node, index) => {
      positions[node.id] = { x: columns[kind] || 150, y: step * (index + 1) };
    });
  }
  return { width, height, positions };
}

function graphNodeText(node) {
  const prefix = node.kind === "tag" ? "#" : "";
  return `${prefix}${node.label}`;
}

function wireGraphNodes() {
  el.graphCanvas.querySelectorAll("g.graph-node[data-route]").forEach((node) => {
    const open = () => go(node.dataset.route);
    node.addEventListener("click", open);
    node.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault(); open();
      }
    });
  });
}

function renderGraphSvg(payload) {
  const { width, height, positions } = graphLayout(payload.nodes || []);
  const lines = (payload.edges || []).map((edge) => {
    const from = positions[edge.from];
    const to = positions[edge.to];
    if (!from || !to) return "";
    const color = GRAPH_EDGE_COLORS[edge.source] || "#9ca3af";
    return `<line class="graph-edge graph-edge-${esc(edge.source)}" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="${color}" />`;
  }).join("");
  const nodes = (payload.nodes || []).map((node) => {
    const point = positions[node.id];
    const label = graphNodeText(node);
    const escaped = esc(label);
    return `<g class="graph-node graph-node-${esc(node.kind)}${node.isolated ? " isolated" : ""}" data-route="${esc(node.route)}" data-node-id="${esc(node.id)}" role="button" tabindex="0" transform="translate(${point.x} ${point.y})">
      <title>${escaped} · ${esc(GRAPH_KIND_LABELS[node.kind] || node.kind)} · ${node.degree} 条关系</title>
      <circle r="${node.kind === "document" ? 26 : 22}"></circle>
      <text text-anchor="middle" dy="4">${escaped.length > 18 ? `${esc(label.slice(0, 17))}…` : escaped}</text>
    </g>`;
  }).join("");
  el.graphCanvas.setAttribute("viewBox", `0 0 ${width} ${height}`);
  el.graphCanvas.innerHTML = `<g class="graph-edges">${lines}</g><g class="graph-nodes">${nodes}</g>`;
  wireGraphNodes();
}

async function renderGraph() {
  el.graphZone.classList.remove("hidden");
  el.graphEmpty.classList.add("hidden");
  el.graphScroll.classList.remove("hidden");
  el.graphCanvas.innerHTML = "";
  el.graphEmpty.querySelector("p").textContent = "暂无可导航的关系图谱。";
  try {
    const graph = await api("/api/graph");
    if (graph.empty) {
      el.graphEmpty.classList.remove("hidden");
      el.graphScroll.classList.add("hidden");
      return;
    }
    renderGraphSvg(graph);
  } catch (e) {
    el.graphEmpty.querySelector("p").textContent = "图谱加载失败。";
    el.graphEmpty.classList.remove("hidden");
    el.graphScroll.classList.add("hidden");
    showToast("加载图谱失败：" + e.message, "err");
  }
}

/* ---------- Dashboard (read-only local telemetry) ---------- */

function dashboardValue(value, digits = 0) {
  if (value == null) return "不可用";
  return typeof value === "number" ? value.toFixed(digits) : String(value);
}

function dashboardCost(item, currency) {
  if (item.cost_status === "no_price_config") return "无价格配置";
  if (item.cost_status === "usage_unavailable" || item.cost_status === "tokens_incomplete") return "token 不可用";
  if (item.cost_status === "cached") return "缓存命中 · 无新增成本";
  if (item.cost == null) return "不可用";
  return `${Number(item.cost).toFixed(6)} ${esc(currency || "USD")}`;
}

function dashboardRows(items, labelKey, valueKey = "count") {
  if (!items || !items.length) return `<span class="dim">暂无数据</span>`;
  return items.map((item) => `<div class="dashboard-row">
    <span>${esc(item[labelKey])}</span><b>${esc(dashboardValue(item[valueKey]))}</b>
  </div>`).join("");
}

function renderDashboardBuckets(items, currency) {
  if (!items || !items.length) return `<span class="dim">暂无 token 遥测</span>`;
  return items.map((item) => `<div class="dashboard-bucket">
    <div><b>${esc(item.period)}</b><span class="dim">${dashboardValue(item.total_tokens)} tokens</span></div>
    <div class="dim">输入 ${dashboardValue(item.prompt_tokens)} · 输出 ${dashboardValue(item.completion_tokens)} · 推理 ${dashboardValue(item.reasoning_tokens)}</div>
    <div class="dashboard-cost">${dashboardCost(item, currency)}</div>
  </div>`).join("");
}

function renderDashboardModels(items, currency) {
  if (!items || !items.length) return `<span class="dim">暂无模型遥测</span>`;
  return `<div class="dashboard-model-list">${items.map((item) => `<div class="dashboard-model">
    <div class="dashboard-model-head"><b>${esc(item.model)}</b><span class="dim">${esc(item.provider || "供应商未知")}</span></div>
    <div class="dashboard-model-meta">${dashboardValue(item.total_tokens)} tokens · ${item.events} 次 · 重试 ${item.retries} 次 · 缓存 ${item.cached_hits} 次</div>
    <div class="dashboard-cost">成本：${dashboardCost(item, currency)}</div>
  </div>`).join("")}</div>`;
}

async function renderDashboard() {
  el.dashboardZone.classList.remove("hidden");
  el.dashboardEmpty.classList.add("hidden");
  el.dashboardContent.classList.remove("hidden");
  try {
    const stats = await api("/api/stats");
    if (stats.empty_library) {
      el.dashboardEmpty.classList.remove("hidden");
      el.dashboardContent.classList.add("hidden");
      return;
    }
    const periods = stats.periods || {};
    el.dashboardPeriods.innerHTML = [
      ["今日解析", periods.today], ["本周解析", periods.week], ["累计解析", periods.total],
    ].map(([label, item]) => `<div class="dashboard-card"><span class="dim">${label}</span><strong>${dashboardValue(item && item.pages)}</strong><small>${dashboardValue(item && item.new_documents)} 个新文档</small></div>`).join("");
    const quality = stats.quality || {};
    const qualityText = quality.status === "complete" ? "遥测完整" : quality.status === "partial" ? `有 ${quality.missing_telemetry_events} 条旧记录缺少遥测` : "遥测不可用";
    el.dashboardQualityLabel.textContent = qualityText;
    el.dashboardQuality.innerHTML = `<div class="dashboard-quality-row"><span>平均耗时</span><b>${dashboardValue(quality.average_latency_seconds, 2)} 秒</b><span>重试率</span><b>${quality.retry_rate == null ? "不可用" : `${(quality.retry_rate * 100).toFixed(1)}%`}</b><span>可用遥测</span><b>${quality.telemetry_events}/${quality.total_events}</b></div>`;
    el.dashboardTrend.innerHTML = dashboardRows(stats.new_documents_trend, "date");
    el.dashboardCategories.innerHTML = dashboardRows(stats.classification_distribution, "topic");
    el.dashboardTags.innerHTML = dashboardRows(stats.top_tags, "tag");
    el.dashboardModels.innerHTML = renderDashboardModels(stats.model_usage, stats.currency);
    el.dashboardDay.innerHTML = renderDashboardBuckets(stats.token_usage_by_day, stats.currency);
    el.dashboardMonth.innerHTML = renderDashboardBuckets(stats.token_usage_by_month, stats.currency);
  } catch (e) {
    el.dashboardEmpty.querySelector("p").textContent = "数据看板加载失败。";
    el.dashboardEmpty.classList.remove("hidden");
    el.dashboardContent.classList.add("hidden");
    showToast("加载数据看板失败：" + e.message, "err");
  }
}

async function renderCollectionNavigation() {
  if (!el.collectionTree) return;
  let collections = [];
  try { collections = await api("/api/collections"); }
  catch (e) { showToast("加载集合失败：" + e.message, "err"); return; }
  el.collectionTree.innerHTML = collections.length ? collections.map((item) => `
    <span class="collection-tree-item ${state.libraryCollection === item.collection_id ? "selected" : ""}">
      <button class="workspace-link collection-open" data-collection-id="${esc(item.collection_id)}">${esc(item.name)} <span class="dim">${item.document_count}</span></button>
      <button class="tag-action" data-collection-action="rename" data-collection-id="${esc(item.collection_id)}">改名</button>
      <button class="tag-action" data-collection-action="delete" data-collection-id="${esc(item.collection_id)}">删除</button>
    </span>`).join("") : `<span class="dim">暂无集合</span>`;
  el.collectionTree.querySelectorAll("button.collection-open").forEach((button) => {
    button.addEventListener("click", () => {
      state.libraryCollection = button.dataset.collectionId;
      state.libraryFilter = "all";
      state.libraryTag = null;
      state.libraryTopic = null;
      renderLibrary();
    });
  });
  el.collectionTree.querySelectorAll("button[data-collection-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const cid = button.dataset.collectionId;
      try {
        if (button.dataset.collectionAction === "delete") {
          await api(`/api/collections/${encodeURIComponent(cid)}`, { method: "DELETE" });
          if (state.libraryCollection === cid) state.libraryCollection = null;
        } else {
          const name = window.prompt("集合重命名为？", cid);
          if (!name || name === cid) return;
          await api(`/api/collections/${encodeURIComponent(cid)}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
          });
        }
        await renderLibrary();
      } catch (e) { showToast("集合操作失败：" + e.message, "err"); }
    });
  });
}

async function renderTagVocabulary() {
  if (!el.tagList) return;
  let tags = [];
  try { tags = await api("/api/tags"); }
  catch (e) { showToast("加载标签词表失败：" + e.message, "err"); return; }
  el.tagList.innerHTML = tags.length ? tags.map((item) => `
    <span class="tag-vocabulary-item">
      <span class="tag-name">#${esc(item.tag)}</span>
      <span class="dim">${item.count} 份${item.aliases && item.aliases.length ? ` · 别名：${esc(item.aliases.join("、"))}` : ""}</span>
      <button class="tag-action" data-tag-action="rename" data-tag="${esc(item.tag)}">重命名</button>
      <button class="tag-action" data-tag-action="merge" data-tag="${esc(item.tag)}">合并</button>
    </span>`).join("") : `<span class="dim">暂无标签，打开文档后可添加。</span>`;
  el.tagList.querySelectorAll("button[data-tag-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = button.dataset.tag;
      const target = window.prompt(button.dataset.tagAction === "merge" ? "合并到哪个标签？" : "重命名为？", source);
      if (!target || target === source) return;
      try {
        await api(`/api/tags/${button.dataset.tagAction}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source, target }),
        });
        await renderTagVocabulary();
        showToast(button.dataset.tagAction === "merge" ? "标签已合并" : "标签已重命名", "ok");
      } catch (e) { showToast("标签治理失败：" + e.message, "err"); }
    });
  });
}

function renderDocumentTags(tags) {
  if (!el.documentTagList) return;
  const values = tags || [];
  el.documentTagList.innerHTML = values.length ? values.map((tag) => `
    <span class="document-tag">#${esc(tag)}<button type="button" data-remove-tag="${esc(tag)}" aria-label="移除 ${esc(tag)}">×</button></span>`).join("")
    : `<span class="dim">暂无标签</span>`;
  el.documentTagList.querySelectorAll("button[data-remove-tag]").forEach((button) => {
    button.addEventListener("click", () => updateDocumentTags(values.filter((tag) => tag !== button.dataset.removeTag)));
  });
}

async function updateDocumentTags(tags) {
  if (!state.docId) return;
  try {
    const result = await api(`/api/documents/${encodeURIComponent(state.docId)}/tags`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags }),
    });
    if (state.doc) state.doc.tags = result.tags;
    renderDocumentTags(result.tags);
  } catch (e) { showToast("文档标签保存失败：" + e.message, "err"); }
}

async function renderDocumentCollections(collectionIds) {
  if (!el.documentCollectionList) return;
  let collections = [];
  try { collections = await api("/api/collections"); } catch (_) { collections = []; }
  const current = collectionIds || [];
  el.documentCollectionSelect.innerHTML = `<option value="">选择集合</option>` + collections
    .filter((item) => !current.includes(item.collection_id))
    .map((item) => `<option value="${esc(item.collection_id)}">${esc(item.name)}</option>`).join("");
  el.documentCollectionList.innerHTML = current.length ? current.map((cid) => {
    const item = collections.find((entry) => entry.collection_id === cid);
    return `<span class="document-tag">${esc(item ? item.name : cid)}<button type="button" data-remove-collection="${esc(cid)}">×</button></span>`;
  }).join("") : `<span class="dim">暂无集合</span>`;
  el.documentCollectionList.querySelectorAll("button[data-remove-collection]").forEach((button) => {
    button.addEventListener("click", () => updateDocumentCollections(current.filter((cid) => cid !== button.dataset.removeCollection)));
  });
}

async function updateDocumentCollections(collectionIds) {
  if (!state.docId) return;
  try {
    const result = await api(`/api/documents/${encodeURIComponent(state.docId)}/collections`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ collection_ids: collectionIds }),
    });
    if (state.doc) state.doc.collections = result.collections;
    await renderDocumentCollections(result.collections);
  } catch (e) { showToast("文档集合保存失败：" + e.message, "err"); }
}

/* ---------- upload ---------- */

function renderUpload() {
  el.uploadZone.classList.remove("hidden");
}

function acceptFile(file) {
  if (!file) return;
  if (!/\.(jpe?g|png)$/i.test(file.name)) {
    el.uploadHint.textContent = "不支持的文件类型：请上传 JPG / JPEG / PNG。"; return;
  }
  if (file.size > 10 * 1024 * 1024) {
    el.uploadHint.textContent = `文件 ${(file.size / 1048576).toFixed(1)}MB 超过 10MB 上限，请压缩后再上传。`;
    return;
  }
  el.uploadHint.textContent = "";
  startUpload(file);
}

async function startUpload(file) {
  if (state.busy) return;
  state.busy = true; setBusy(true);
  showWorking("正在上传…", file.name);
  try {
    const r = await api("/api/parse", {
      method: "POST",
      body: (() => { const f = new FormData(); f.append("file", file); return f; })(),
    });
    state.jobId = r.job_id;
    pollJob(r.document_id);
  } catch (e) {
    state.busy = false; setBusy(false);
    renderUpload();
    el.uploadHint.textContent = e.message;
  }
}

/* ---------- job poll (fresh parse / reparse) => open document ---------- */

function showWorking(text, detail) {
  hideAll();
  el.workingZone.classList.remove("hidden");
  el.workingText.textContent = text;
  el.workingDetail.textContent = detail || "";
}

function pollJob(docId, thenRoute) {
  showWorking("解析中…", "正在预处理 → 识别 → 渲染，请稍候");
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    let job;
    try { job = await api(`/api/jobs/${state.jobId}`); }
    catch (e) { clearInterval(state.pollTimer); showToast("查询任务失败：" + e.message, "err"); go("#library"); return; }
    if (job.status === "queued" || job.status === "processing") return;
    clearInterval(state.pollTimer);
    state.busy = false; setBusy(false);
    if (job.status === "done") {
      const did = docId || job.document_id;
      if (thenRoute && thenRoute === "reload") { go(`#doc/${encodeURIComponent(did)}`); }
      else { go(`#doc/${encodeURIComponent(did)}`); }
    } else {
      // failed / timeout — return to library with a clear message
      showToast((job.error || (job.error_kind === "timeout" ? "解析超时" : "解析失败")) +
                "，可重新解析或重试。", "err");
      go("#library");
    }
  }, POLL_MS);
}

/* ---------- document (three-pane) ---------- */

async function renderDocument(id) {
  hideAll();
  el.workZone.classList.remove("hidden");
  setBusy(true);
  try {
    const doc = await api(`/api/documents/${encodeURIComponent(id)}`);
    state.doc = doc;
    setBusy(false);
    el.mdEditor.value = doc.current_markdown || "";
    el.mdEditor.disabled = false;
    renderPreview(doc.current_markdown || "");
    setDocImage(id);
    el.modelLabel.textContent = "模型：" + (doc.latest && doc.latest.model) || "";
    el.versionInfo.textContent = doc.versions && doc.versions.length > 1
      ? `第 ${doc.versions.length} 版（历史 ${doc.versions.length - 1} 版留存）` : "第 1 版";
    el.warnings.textContent = "";
    renderDocumentTags(doc.tags);
    await renderDocumentCollections(doc.collections);
    renderMetadata(doc.metadata);
    el.statusText.textContent = doc.current_markdown && doc.current_markdown.trim()
      ? "文档已载入，编辑自动保存 ✓" : "空文档：未识别出可渲染内容。";
    el.saveIndicator.textContent = "";
  } catch (e) {
    setBusy(false);
    showToast("打开文档失败：" + e.message, "err");
    go("#library");
  }
}

function setDocImage(id) {
  el.originalImg.src = `/api/documents/${encodeURIComponent(id)}/preprocessed`;
  el.originalImg.onerror = () => {
    el.originalImg.src = `/api/documents/${encodeURIComponent(id)}/original`;
  };
}

function displayTime(value) {
  return value ? String(value).replace("T", " ") : "未记录";
}

function renderMetadata(metadata) {
  const m = metadata || {};
  const doc = m.document_time || {};
  const capture = m.capture_time || {};
  const imported = m.import_time || {};
  const modified = m.modified_time || {};
  el.metadataDocumentTime.value = doc.value || "";
  if (el.metadataNeedsOrganization) {
    el.metadataNeedsOrganization.checked = Boolean(m.needs_organization);
  }
  el.metadataCaptureTime.textContent = displayTime(capture.value);
  el.metadataImportTime.textContent = displayTime(imported.value);
  el.metadataModifiedTime.textContent = displayTime(modified.value);
  const effective = m.effective_time;
  const parts = [];
  if (effective && effective.value) {
    parts.push(`时间轴采用：${displayTime(effective.value)}（${effective.source || effective.field}）`);
  }
  if (doc.evidence) {
    parts.push(`手稿日期依据：${doc.evidence}`);
    if (doc.confidence) parts.push(`置信度：${doc.confidence}`);
  }
  el.metadataEvidence.textContent = parts.join(" · ") || "暂无日期推断依据";
  el.metadataSave.textContent = "";
}

async function saveDocumentMetadata() {
  if (!state.docId || !el.metadataDocumentTime) return;
  el.metadataSave.textContent = "保存中…";
  try {
    const result = await api(`/api/documents/${encodeURIComponent(state.docId)}/metadata`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_time: el.metadataDocumentTime.value || null,
        needs_organization: Boolean(el.metadataNeedsOrganization && el.metadataNeedsOrganization.checked),
      }),
    });
    if (state.doc) state.doc.metadata = result.metadata;
    renderMetadata(result.metadata);
    el.metadataSave.textContent = "已保存";
  } catch (e) {
    el.metadataSave.textContent = "保存失败";
    showToast("时间元数据保存失败：" + e.message, "err");
  }
}

/* ---------- editable markdown + autosave + live preview ---------- */

/* Current preview context for re-writing relative ``assets/`` image refs to
   the owning API URL (issue 06b).  ``doc`` view is the document library route;
   ``job`` view is the fresh-parse/working context. */
function currentPreviewContext() {
  const r = parseHash();
  if (r.name === "doc" && state.docId) return { kind: "doc", id: state.docId };
  if (state.jobId) return { kind: "job", id: state.jobId };
  return null;
}

let markedPrepared = false;

/* Install a marked image renderer that re-writes ``assets/<name>`` refs to the
   context asset endpoint.  Runs once; non-asset refs keep marked's default.
   Tolerates both marked signatures: v4 (href, title, text) strings and
   v12+ token object (normalized by assets.js, issue 06c). */
function ensureMarkedPrepared() {
  if (markedPrepared || !window.marked || !window.marked.Renderer) return;
  if (!window.__g2nAssets) return;      // assets.js not loaded -> leave refs as-is
  markedPrepared = true;
  const Renderer = window.marked.Renderer;
  const renderer = new Renderer();
  renderer.image = function (hrefOrToken, title, text) {
    const a = window.__g2nAssets.normalizeImageArgs(hrefOrToken, title, text);
    const ctx = currentPreviewContext();
    const src = ctx ? window.__g2nAssets.resolveAssetSrc(a.href, ctx.kind, ctx.id) : a.href;
    let attrs = `src="${src}" alt="${esc(a.text || "")}"`;
    if (a.title) attrs += ` title="${esc(a.title)}"`;
    return `<img ${attrs}>`;
  };
  window.marked.use({ renderer });
}

function renderPreview(md) {
  const out = el.preview;
  out.innerHTML = "";
  try {
    if (!window.marked && window.__mdMissing) {
      out.innerHTML = `<div class="preview-error">⚠ 预览库（marked）未能加载，无法渲染；编辑不受影响。</div>`;
      return;
    }
    if (!window.marked) {
      out.innerHTML = `<div class="preview-error">预览引擎加载中…（编辑不受影响）</div>`;
      return;
    }
    ensureMarkedPrepared();
    out.innerHTML = window.marked.parse(md || "");
    if (window.renderMathInElement) {
      renderMathInElement(out, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
        ],
        throwOnError: false,
      });
    }
  } catch (e) {
    out.innerHTML = `<div class="preview-error">⚠ 预览渲染失败：${esc(e.message)}</div>`;
  }
}

let previewDebounce = null;
let saveTimer = null;
el.mdEditor.addEventListener("input", () => {
  clearTimeout(previewDebounce);
  previewDebounce = setTimeout(() => renderPreview(el.mdEditor.value), 180);
  scheduleSave();
});

function scheduleSave() {
  clearTimeout(saveTimer);
  el.saveIndicator.textContent = "保存中…";
  saveTimer = setTimeout(() => autosave(el.mdEditor.value), SAVE_MS);
}

async function autosave(markdown) {
  if (!state.docId) return;
  try {
    await api(`/api/documents/${encodeURIComponent(state.docId)}/markdown`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown }),
    });
    el.saveIndicator.textContent = "已保存 " + new Date().toLocaleTimeString();
  } catch (e) {
    el.saveIndicator.textContent = "保存失败";
    showToast("编辑保存失败：" + e.message, "err");
  }
}

/* ---------- actions ---------- */

el.btnReparse.onclick = async () => {
  if (state.busy || !state.docId) return;
  const ok = window.confirm(
    "重新解析将用新的识别结果覆盖当前 Markdown（您的编辑将被替换，旧内容仍在历史版本可查）。确定继续吗？");
  if (!ok) return;
  state.busy = true; setBusy(true);
  try {
    const r = await api(`/api/documents/${encodeURIComponent(state.docId)}/reparse`, {
      method: "POST",
    });
    state.jobId = r.job_id;
    pollJob(state.docId);
  } catch (e) {
    state.busy = false; setBusy(false);
    showToast("发起重新解析失败：" + e.message, "err");
  }
};

el.btnCopy.onclick = async () => {
  const text = el.mdEditor.value;
  try { await navigator.clipboard.writeText(text); showToast("已复制 Markdown 到剪贴板", "ok"); }
  catch (e) {
    el.mdEditor.select(); document.execCommand("copy"); showToast("已复制（回退方式）", "ok");
  }
};

el.btnDownload.onclick = async () => {
  if (state.busy || !state.docId) return;
  state.busy = true; setBusy(true);
  try {
    const zip = await api(`/api/documents/${encodeURIComponent(state.docId)}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: el.mdEditor.value }),
    });
    const url = URL.createObjectURL(zip);
    const a = document.createElement("a");
    a.href = url;
    a.download = (state.doc && state.doc.title || "note").replace(/[\\/:*?"<>|]/g, "_") + ".zip";
    a.click();
    URL.revokeObjectURL(url);
    showToast("已下载 .md + 附件（zip）", "ok");
  } catch (e) { showToast("导出失败：" + e.message, "err"); }
  state.busy = false; setBusy(false);
};

el.btnDelete.onclick = async () => {
  if (!state.docId) return;
  const ok = window.confirm("删除文档将移除原图、识别结果、Markdown 与全部附件，且不可恢复。确定删除？");
  if (!ok) return;
  try {
    await api(`/api/documents/${encodeURIComponent(state.docId)}`, { method: "DELETE" });
    showToast("文档已删除", "ok");
    go("#library");
  } catch (e) { showToast("删除失败：" + e.message, "err"); }
};

el.btnRepic.onclick = () => state.docId && setDocImage(state.docId);
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
    await renderLibrary();
  } catch (e) { showToast("新建集合失败：" + e.message, "err"); }
});
document.querySelectorAll("button[data-library-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.libraryCollection = null;
    state.libraryTag = null;
    state.libraryTopic = null;
    state.libraryFilter = button.dataset.libraryFilter;
    renderLibrary();
  });
});
el.documentTagForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = el.documentTagInput.value.trim();
  if (!value || !state.doc) return;
  el.documentTagInput.value = "";
  updateDocumentTags([...(state.doc.tags || []), value]);
});
el.documentCollectionForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = el.documentCollectionSelect.value;
  if (!value || !state.doc) return;
  el.documentCollectionSelect.value = "";
  updateDocumentCollections([...(state.doc.collections || []), value]);
});
el.tagCreateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = el.tagCreateInput.value.trim();
  if (!value) return;
  try {
    await api("/api/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: value }),
    });
    el.tagCreateInput.value = "";
    await renderTagVocabulary();
  } catch (e) { showToast("新增标签失败：" + e.message, "err"); }
});
el.metadataDocumentTime.addEventListener("change", saveDocumentMetadata);
el.metadataNeedsOrganization.addEventListener("change", saveDocumentMetadata);
el.navLibrary.onclick = () => go("#library");
el.navInbox.onclick = () => go("#inbox");
el.navTimeline.onclick = () => go("#timeline/day");
el.navGraph.onclick = () => go("#graph");
el.navDashboard.onclick = () => go("#dashboard");
el.navSettings.onclick = () => go("#settings");
el.navVaultExport.onclick = () => go("#vault-export");
el.navUpload.onclick = () => go("#upload");
el.vaultExportForm.addEventListener("submit", (event) => {
  event.preventDefault();
  startVaultExport();
});
el.timelineGroup.addEventListener("change", () => go(`#timeline/${el.timelineGroup.value}`));
el.llmSaveButton.addEventListener("click", saveLlmSettings);
el.llmHealthButton.addEventListener("click", checkLlmHealth);

/* ---------- upload wiring ---------- */

el.pickFile.onclick = () => el.fileInput.click();
el.fileInput.addEventListener("change", (e) => acceptFile(e.target.files[0]));

/* ---------- PDF upload (issue 08) ---------- */

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
    renderUpload();
    el.uploadHint.textContent = e.message;
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

el.pickPdf.onclick = () => el.pdfInput.click();
el.pdfInput.addEventListener("change", (e) => acceptPdf(e.target.files[0]));
el.pdfRetry.addEventListener("click", () => {
  if (state.pdfId) retryPdf(state.pdfId);
});

["dragenter", "dragover"].forEach((ev) =>
  el.uploadCard.addEventListener(ev, (e) => { e.preventDefault(); el.uploadCard.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) =>
  el.uploadCard.addEventListener(ev, (e) => { e.preventDefault(); el.uploadCard.classList.remove("drag"); }));
el.uploadCard.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) acceptFile(f);
});

/* ---------- boot ---------- */
render();
window.addEventListener("beforeunload", () => {
  // flush any pending autosave on exit
  clearTimeout(saveTimer);
  if (state.docId && el.mdEditor.value !== (state.doc && state.doc.current_markdown)) {
    void autosave(el.mdEditor.value);
  }
});
