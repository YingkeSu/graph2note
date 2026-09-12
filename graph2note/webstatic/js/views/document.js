/* graph2note — three-pane document view: load, metadata, tags/collections,
   autosave, live preview and document actions (U1 relocation; U3 will reshape
   the workspace internals). */
"use strict";

import { el, state, setBusy } from "../state.js";
import { api } from "../api.js";
import { esc, displayTime, SAVE_MS } from "../utils.js";
import { parseHash, go, registerView } from "../router.js";
import { showToast } from "../ui.js";
import { pollJob } from "../jobs.js";

/* ---------- document (three-pane) ---------- */

async function renderDocument(id) {
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

function renderDocumentRoute(route) {
  state.docId = route.id;
  renderDocument(route.id);
}

function setDocImage(id) {
  el.originalImg.src = `/api/documents/${encodeURIComponent(id)}/preprocessed`;
  el.originalImg.onerror = () => {
    el.originalImg.src = `/api/documents/${encodeURIComponent(id)}/original`;
  };
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

/* ---------- document tags / collections ---------- */

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

export function renderPreview(md) {
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

/* Flush a pending autosave on unload (registered by app.js entry). */
export function flushAutosave() {
  clearTimeout(saveTimer);
  if (state.docId && el.mdEditor.value !== (state.doc && state.doc.current_markdown)) {
    void autosave(el.mdEditor.value);
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
el.documentCollectionForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = el.documentCollectionSelect.value;
  if (!value || !state.doc) return;
  el.documentCollectionSelect.value = "";
  updateDocumentCollections([...(state.doc.collections || []), value]);
});

el.metadataDocumentTime.addEventListener("change", saveDocumentMetadata);
el.metadataNeedsOrganization.addEventListener("change", saveDocumentMetadata);

registerView("doc", renderDocumentRoute);
