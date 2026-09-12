/* graph2note — document editor workspace (U3).

   Layout: a permanent toolbar (autosave indicator + warnings + document
   actions) above the three-pane axis; tags / collections / time metadata /
   needs-organization / version info live in a collapsible right-hand side
   panel; a full-screen image viewer (zoom / pan / fit) opens from the
   original-image pane for image uploads and PDF source pages alike.

   Behaviour is unchanged from the pre-U3 three-pane view: every side-panel
   form still drives the same API and updates the same shared state.  The A1
   auto/manual tag provenance (「自动」badge, one-click promote, remove) is
   preserved verbatim — only its container moved.
*/
"use strict";

import { el, state, setBusy } from "../state.js";
import { api } from "../api.js";
import { esc, displayTime, SAVE_MS } from "../utils.js";
import { parseHash, go, registerView } from "../router.js";
import { showToast } from "../ui.js";
import { pollJob } from "../jobs.js";
import {
  configureVersionDiff,
  renderVersionPanel,
  closeCompare,
  openCompare,
  handleVersionDiffShortcut,
} from "./version-diff.js";

/* ---------- document (three-pane) ---------- */

async function renderDocument(id, route) {
  closeImageViewer();
  closeCompare();
  toggleSidePanel(false);            // 默认收起：编辑 Markdown 时零干扰
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
    renderVersions(doc);
    void renderVersionPanel(id);      // S3: enrich the switcher with source + diff badges
    el.warnings.textContent = "";
    renderDocumentTags(doc.tags, doc.tag_provenance);
    await renderDocumentCollections(doc.collections);
    renderMetadata(doc.metadata);
    el.statusText.textContent = doc.current_markdown && doc.current_markdown.trim()
      ? "文档已载入，编辑自动保存 ✓" : "空文档：未识别出可渲染内容。";
    el.saveIndicator.textContent = "";
    if (route && route.compare) {
      void openCompare({ a: route.versionA, b: route.versionB });
    } else if (route && route.panel) {
      toggleSidePanel(true);            // deep link to the version switcher
    }
  } catch (e) {
    setBusy(false);
    showToast("打开文档失败：" + e.message, "err");
    go("#library");
  }
}

export function renderDocumentRoute(route) {
  state.docId = route.id;
  renderDocument(route.id, route);
}

function setDocImage(id) {
  el.originalImg.src = `/api/documents/${encodeURIComponent(id)}/preprocessed`;
  el.originalImg.onerror = () => {
    el.originalImg.src = `/api/documents/${encodeURIComponent(id)}/original`;
  };
}

/* ---------- version info (side panel; S3 version-diff mount point) ---------- */

/* Renders the read-only version index into ``#version-info`` + ``#version-list``.
   The version mechanism is untouched; S3 mounts its compare UI inside
   ``#version-panel`` (see handoff for the API contract). */
export function renderVersions(doc) {
  const versions = (doc && doc.versions) || [];
  if (el.versionInfo) {
    el.versionInfo.textContent = versions.length > 1
      ? `第 ${versions.length} 版（历史 ${versions.length - 1} 版留存）` : "第 1 版";
  }
  if (!el.versionList) return;
  const latestId = doc && doc.latest_version;
  el.versionList.innerHTML = versions.length
    ? versions.slice().reverse().map((v, index) => {
      const isCurrent = (latestId && v.version_id === latestId) || (!latestId && index === 0);
      const prov = v.provenance ? `<span class="version-prov">${esc(v.provenance)}</span>` : "";
      return `<div class="version-item${isCurrent ? " current" : ""}" data-version-id="${esc(v.version_id)}">
        <span class="version-badge">${isCurrent ? "当前" : "历史"}</span>
        <span class="version-time dim">${esc(displayTime(v.created_at))}</span>
        <span class="version-model dim">${esc(v.model || "")}</span>${prov}
      </div>`;
    }).join("")
    : `<span class="dim">暂无版本记录</span>`;
}

/* ---------- metadata ---------- */

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

/* ---------- document tags / collections (A1 provenance preserved) ---------- */

function renderDocumentTags(tags, provenance) {
  if (!el.documentTagList) return;
  const values = tags || [];
  const prov = provenance || {};
  el.documentTagList.innerHTML = values.length ? values.map((tag) => {
    const isAuto = (prov[tag] || "manual") === "auto";
    const badge = isAuto
      ? `<span class="tag-auto-badge" title="识别结果自动打标">自动</span>` : "";
    const keep = isAuto
      ? `<button type="button" class="tag-promote" data-promote-tag="${esc(tag)}" title="保留为手工标签" aria-label="保留 ${esc(tag)} 为手工标签">✓</button>` : "";
    return `<span class="document-tag${isAuto ? " auto" : ""}" data-tag="${esc(tag)}">#${esc(tag)}${badge}${keep}<button type="button" data-remove-tag="${esc(tag)}" aria-label="移除 ${esc(tag)}">×</button></span>`;
  }).join("")
    : `<span class="dim">暂无标签</span>`;
  el.documentTagList.querySelectorAll("button[data-remove-tag]").forEach((button) => {
    button.addEventListener("click", () => removeDocumentTag(button.dataset.removeTag));
  });
  el.documentTagList.querySelectorAll("button[data-promote-tag]").forEach((button) => {
    button.addEventListener("click", () => promoteDocumentTag(button.dataset.promoteTag));
  });
}

function applyTagResult(result) {
  if (!state.doc) return;
  state.doc.tags = result.tags || [];
  state.doc.tag_provenance = result.tag_provenance || {};
  state.doc.tags_detail = result.tags_detail || [];
  renderDocumentTags(state.doc.tags, state.doc.tag_provenance);
}

export async function removeDocumentTag(tag) {
  if (!state.docId) return;
  try {
    const result = await api(`/api/documents/${encodeURIComponent(state.docId)}/tags/${encodeURIComponent(tag)}`, { method: "DELETE" });
    applyTagResult(result);
  } catch (e) { showToast("移除标签失败：" + e.message, "err"); }
}

export async function promoteDocumentTag(tag) {
  if (!state.docId) return;
  try {
    const result = await api(`/api/documents/${encodeURIComponent(state.docId)}/tags/${encodeURIComponent(tag)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provenance: "manual" }),
    });
    applyTagResult(result);
    showToast("已保留为手工标签", "ok");
  } catch (e) { showToast("保留标签失败：" + e.message, "err"); }
}

export async function addDocumentTag(tag) {
  if (!state.docId) return;
  try {
    const result = await api(`/api/documents/${encodeURIComponent(state.docId)}/tags/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag }),
    });
    applyTagResult(result);
  } catch (e) { showToast("添加标签失败：" + e.message, "err"); }
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

export async function updateDocumentCollections(collectionIds) {
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

/* ---------- collapsible info side panel ---------- */

export function isSidePanelOpen() {
  return Boolean(el.docSidePanel && !el.docSidePanel.classList.contains("hidden"));
}

/* ``force`` true = open, false = close, undefined = toggle. */
export function toggleSidePanel(force) {
  if (!el.docSidePanel) return isSidePanelOpen();
  const collapse = force === undefined ? isSidePanelOpen() : !force;
  el.docSidePanel.classList.toggle("hidden", collapse);
  if (el.docPanelToggle) el.docPanelToggle.setAttribute("aria-expanded", String(!collapse));
  return !collapse;
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

/* Render Markdown into any container (document preview + A2 digest viewer).
   Kept as one shared helper so the digest keeps the exact same marked/KaTeX
   pipeline as the editor preview. */
export function renderMarkdownInto(out, md) {
  if (!out) return;
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

export function renderPreview(md) {
  renderMarkdownInto(el.preview, md);
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

/* Shared markdown save.  ``explicit`` (⌘S) is the same request as autosave,
   with a distinct "已保存（⌘S）" confirmation. */
async function saveMarkdown(markdown, explicit = false) {
  if (!state.docId) return;
  try {
    await api(`/api/documents/${encodeURIComponent(state.docId)}/markdown`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown }),
    });
    if (state.doc) state.doc.current_markdown = markdown;
    el.saveIndicator.textContent = "已保存 " + new Date().toLocaleTimeString()
      + (explicit ? "（⌘S）" : "");
  } catch (e) {
    el.saveIndicator.textContent = "保存失败";
    showToast("编辑保存失败：" + e.message, "err");
  }
}

function autosave(markdown) {
  return saveMarkdown(markdown, false);
}

/* ⌘S: flush the debounced autosave immediately and save explicitly. */
export function explicitSave() {
  if (!state.docId) return Promise.resolve();
  clearTimeout(saveTimer);
  el.saveIndicator.textContent = "保存中…";
  return saveMarkdown(el.mdEditor.value, true);
}

/* Flush a pending autosave on unload (registered by app.js entry). */
export function flushAutosave() {
  clearTimeout(saveTimer);
  if (state.docId && el.mdEditor.value !== (state.doc && state.doc.current_markdown)) {
    void autosave(el.mdEditor.value);
  }
}

/* ---------- large image viewer (image upload + PDF source page) ---------- */

const VIEWER_MIN = 0.1;
const VIEWER_MAX = 8;
const VIEWER_STEP = 1.25;

const viewer = { scale: 1, x: 0, y: 0, dragging: false, sx: 0, sy: 0, ox: 0, oy: 0 };

const clampScale = (value) => Math.max(VIEWER_MIN, Math.min(VIEWER_MAX, value));

function hasPdfSource(doc) {
  return Boolean(doc && doc.pdf_id != null && doc.page_index != null);
}

/* Full-resolution source for the viewer: the PDF source page when the document
   came from a PDF (``/api/pdf/{id}/page/{n}`` via the document endpoint), else
   the enhanced preprocessed manuscript (falling back to the raw original). */
export function viewerSource() {
  if (!state.docId) return "";
  const id = encodeURIComponent(state.docId);
  if (hasPdfSource(state.doc)) return `/api/documents/${id}/source-page`;
  return `/api/documents/${id}/preprocessed`;
}

function applyViewerTransform() {
  viewer.scale = clampScale(viewer.scale);
  if (el.imageViewerImg) {
    el.imageViewerImg.style.transform =
      `translate(${viewer.x}px, ${viewer.y}px) scale(${viewer.scale})`;
    el.imageViewerImg.style.transformOrigin = "0 0";
  }
  if (el.viewerZoomLabel) {
    el.viewerZoomLabel.textContent = Math.round(viewer.scale * 100) + "%";
  }
}

export function fitImageViewer() {
  if (!el.imageViewerImg || !el.imageViewerStage) return;
  const natW = el.imageViewerImg.naturalWidth || 0;
  const natH = el.imageViewerImg.naturalHeight || 0;
  const boxW = el.imageViewerStage.clientWidth || 0;
  const boxH = el.imageViewerStage.clientHeight || 0;
  if (natW && natH && boxW && boxH) {
    viewer.scale = clampScale(Math.min(boxW / natW, boxH / natH));
    viewer.x = Math.max(0, (boxW - natW * viewer.scale) / 2);
    viewer.y = Math.max(0, (boxH - natH * viewer.scale) / 2);
  } else {
    viewer.scale = 1;
    viewer.x = 0;
    viewer.y = 0;
  }
  applyViewerTransform();
}

/* Zoom by ``factor`` keeping the point under (clientX, clientY) fixed. */
export function zoomImageViewer(factor, clientX, clientY) {
  if (!el.imageViewer || el.imageViewer.classList.contains("hidden")) return viewer.scale;
  const stage = el.imageViewerStage;
  const box = stage && stage.getBoundingClientRect
    ? stage.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
  const px = (clientX == null ? box.left + box.width / 2 : clientX) - (box.left || 0);
  const py = (clientY == null ? box.top + box.height / 2 : clientY) - (box.top || 0);
  const previous = viewer.scale;
  const next = clampScale(previous * factor);
  if (previous > 0) {
    viewer.x = px - (px - viewer.x) * (next / previous);
    viewer.y = py - (py - viewer.y) * (next / previous);
  }
  viewer.scale = next;
  applyViewerTransform();
  return viewer.scale;
}

/* Open the viewer for ``src`` when given, else for the document's own
   full-resolution source (image upload / PDF page).  S3 passes a per-version
   preprocessed URL so historical original images reuse the same viewer. */
export function openImageViewer(src) {
  if (!state.docId || !el.imageViewer) return;
  const resolved = src || viewerSource();
  if (!resolved) return;
  if (el.imageViewerImg) {
    delete el.imageViewerImg.dataset.fallback;
    el.imageViewerImg.onerror = src ? null : () => {
      const fallback = `/api/documents/${encodeURIComponent(state.docId)}/original`;
      if (!el.imageViewerImg.dataset.fallback) {
        el.imageViewerImg.dataset.fallback = "1";
        el.imageViewerImg.src = fallback;
      }
    };
    el.imageViewerImg.src = resolved;
    el.imageViewerImg.style.transform = "";
    if (el.imageViewerImg.complete && el.imageViewerImg.naturalWidth) {
      fitImageViewer();
    } else {
      el.imageViewerImg.addEventListener("load", fitImageViewer, { once: true });
    }
  }
  viewer.scale = 1; viewer.x = 0; viewer.y = 0;
  el.imageViewer.classList.remove("hidden");
  el.imageViewer.setAttribute("aria-hidden", "false");
  if (el.viewerClose) el.viewerClose.focus();
}

export function closeImageViewer() {
  if (!el.imageViewer) return;
  viewer.dragging = false;
  el.imageViewer.classList.add("hidden");
  el.imageViewer.setAttribute("aria-hidden", "true");
}

export function isImageViewerOpen() {
  return Boolean(el.imageViewer && !el.imageViewer.classList.contains("hidden"));
}

function onViewerWheel(event) {
  event.preventDefault();
  zoomImageViewer(event.deltaY < 0 ? 1.15 : 1 / 1.15, event.clientX, event.clientY);
}

function onStagePointerDown(event) {
  if (!isImageViewerOpen()) return;
  viewer.dragging = true;
  viewer.sx = event.clientX;
  viewer.sy = event.clientY;
  viewer.ox = viewer.x;
  viewer.oy = viewer.y;
  if (el.imageViewerStage && el.imageViewerStage.setPointerCapture && event.pointerId != null) {
    try { el.imageViewerStage.setPointerCapture(event.pointerId); } catch (_) { /* ignore */ }
  }
  if (el.imageViewerImg) el.imageViewerImg.classList.add("dragging");
  event.preventDefault && event.preventDefault();
}

function onStagePointerMove(event) {
  if (!viewer.dragging) return;
  viewer.x = viewer.ox + (event.clientX - viewer.sx);
  viewer.y = viewer.oy + (event.clientY - viewer.sy);
  applyViewerTransform();
  event.preventDefault && event.preventDefault();
}

function onStagePointerUp() {
  viewer.dragging = false;
  if (el.imageViewerImg) el.imageViewerImg.classList.remove("dragging");
}

/* ---------- keyboard shortcuts ---------- */

/* True when focus is in a text field: ⌘/ and Esc must not hijack typing
   (⌘S is exempt — it always saves). */
export function isTextInputFocused() {
  const active = document.activeElement;
  if (!active) return false;
  const tag = (active.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select"
    || active.isContentEditable === true;
}

export function handleEditorShortcut(event) {
  const key = (event.key || "").toLowerCase();
  const mod = event.metaKey || event.ctrlKey;
  if (mod && key === "s") {
    event.preventDefault();
    void explicitSave();
    return true;
  }
  if (mod && event.key === "/") {
    if (isTextInputFocused()) return false;
    event.preventDefault();
    toggleSidePanel();
    return true;
  }
  if (event.key === "Escape") {
    // The viewer is the topmost layer: Esc always returns to the editor.
    if (isImageViewerOpen()) {
      event.preventDefault();
      closeImageViewer();
      return true;
    }
    if (handleVersionDiffShortcut(event)) return true;
    if (!isTextInputFocused() && isSidePanelOpen()) {
      toggleSidePanel(false);
      return true;
    }
  }
  return false;
}

document.addEventListener("keydown", handleEditorShortcut);

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

/* ---------- side-panel + viewer wiring ---------- */

if (el.docPanelToggle) el.docPanelToggle.addEventListener("click", () => toggleSidePanel());
if (el.docPanelClose) el.docPanelClose.addEventListener("click", () => toggleSidePanel(false));
if (el.btnZoomImage) el.btnZoomImage.addEventListener("click", openImageViewer);
if (el.originalImg) {
  el.originalImg.addEventListener("click", openImageViewer);
  el.originalImg.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openImageViewer(); }
  });
}
if (el.viewerClose) el.viewerClose.addEventListener("click", closeImageViewer);
if (el.viewerFit) el.viewerFit.addEventListener("click", () => fitImageViewer());
if (el.viewerZoomIn) el.viewerZoomIn.addEventListener("click", () => zoomImageViewer(VIEWER_STEP));
if (el.viewerZoomOut) el.viewerZoomOut.addEventListener("click", () => zoomImageViewer(1 / VIEWER_STEP));
if (el.imageViewerStage) {
  el.imageViewerStage.addEventListener("wheel", onViewerWheel, { passive: false });
  el.imageViewerStage.addEventListener("pointerdown", onStagePointerDown);
  el.imageViewerStage.addEventListener("pointermove", onStagePointerMove);
  el.imageViewerStage.addEventListener("pointerup", onStagePointerUp);
  el.imageViewerStage.addEventListener("pointercancel", onStagePointerUp);
}

/* S3: hand the version-diff view the shared large-image viewer + the same
   Markdown pipeline as the editor preview (no circular import). */
configureVersionDiff({ openImageViewer, renderMarkdown: renderBlockMarkdownForVersion });

function renderBlockMarkdownForVersion(markdown) {
  if (!window.marked) return `<p>${esc(markdown || "")}</p>`;
  try {
    // Same marked pipeline (and asset-ref rewriting) as the editor preview.
    ensureMarkedPrepared();
    const html = window.marked.parse(markdown || "");
    if (!window.renderMathInElement) return html;
    const holder = document.createElement("div");
    holder.innerHTML = html;
    renderMathInElement(holder, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
    });
    return holder.innerHTML;
  } catch (_) {
    return `<p>${esc(markdown || "")}</p>`;
  }
}

/* ---------- form wiring (unchanged API contracts) ---------- */

el.documentTagForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const value = el.documentTagInput.value.trim();
  if (!value || !state.doc) return;
  el.documentTagInput.value = "";
  addDocumentTag(value);
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
