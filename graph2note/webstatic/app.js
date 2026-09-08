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
  // lazy-load thumbnails
  requestAnimationFrame(() => {
    el.libraryGrid.querySelectorAll("img[data-src]").forEach((img) => {
      img.src = img.dataset.src;
      img.removeAttribute("data-src");
      img.onerror = () => { img.remove(); };
    });
  });
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

/* ---------- editable markdown + autosave + live preview ---------- */

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