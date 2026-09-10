/* graph2note — local document library + three-pane review/edit.
   Views routed by location.hash: #library (home), #upload, #doc/<id>. */
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
};

const el = {
  libraryZone: $("#library-zone"),
  libraryGrid: $("#library-grid"),
  libraryEmpty: $("#library-empty"),
  libraryCount: $("#library-count"),
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
  navUpload: $("#nav-upload"),
  modelLabel: $("#model-label"),
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
  if (parts[0] === "upload") return { name: "upload" };
  return { name: "library" };
}

function render() {
  const r = parseHash();
  state.route = r.name;
  hideAll();
  if (r.name === "upload") { renderUpload(); }
  else if (r.name === "doc") { state.docId = r.id; renderDocument(r.id); }
  else { renderLibrary(); }
}

function hideAll() {
  [el.libraryZone, el.uploadZone, el.workingZone, el.workZone]
    .forEach((n) => n.classList.add("hidden"));
}

window.addEventListener("hashchange", render);

/* ---------- library ---------- */

async function renderLibrary() {
  el.libraryZone.classList.remove("hidden");
  el.libraryGrid.innerHTML = "";
  let docs = [];
  try { docs = await api("/api/documents"); }
  catch (e) { showToast("加载文档库失败：" + e.message, "err"); }
  el.libraryCount.textContent = docs.length ? `共 ${docs.length} 份` : "";
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
  await renderTagVocabulary();
  // lazy-load thumbnails
  requestAnimationFrame(() => {
    el.libraryGrid.querySelectorAll("img[data-src]").forEach((img) => {
      img.src = img.dataset.src;
      img.removeAttribute("data-src");
      img.onerror = () => { img.remove(); };
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
      body: JSON.stringify({ document_time: el.metadataDocumentTime.value || null }),
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
el.documentTagForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = el.documentTagInput.value.trim();
  if (!value || !state.doc) return;
  el.documentTagInput.value = "";
  updateDocumentTags([...(state.doc.tags || []), value]);
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
el.navLibrary.onclick = () => go("#library");
el.navUpload.onclick = () => go("#upload");

/* ---------- upload wiring ---------- */

el.pickFile.onclick = () => el.fileInput.click();
el.fileInput.addEventListener("change", (e) => acceptFile(e.target.files[0]));
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
