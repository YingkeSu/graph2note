/* graph2note — version switcher + comparison view (issue S3).

   Lives inside the U3 editor workspace: the side panel's version list gains
   source + diff badges (S2 chain) and the editor opens a read-only compare
   overlay (``#diff-view``) for any two versions.  Highlights, statistics and
   anchors all come from S1's ``DiffReport`` served by
   ``GET /api/documents/{id}/diff`` — this module never re-implements a text
   diff.  The summary bar is backend-templated (zero model calls).

   Read-only red line: viewing a historical version never edits it; the
   Markdown editor keeps autosaving the *latest* version, and the overlay shows
   an explicit "历史版本（只读）" notice + a way back to the latest.
*/
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { showToast } from "../ui.js";
import * as core from "../version_diff_core.js";

/* Injected by document.js (avoids a circular import): the U3 large-image
   viewer is reused for the two per-version original images. */
const hooks = { openImageViewer: null, renderMarkdown: null };

export function configureVersionDiff(next = {}) {
  Object.assign(hooks, next);
}

let chainCache = null;        // { documentId, chain }
let currentPayload = null;
let selectedVersion = null;   // version id selected in the switcher

export function isCompareOpen() {
  return Boolean(el.diffView && !el.diffView.classList.contains("hidden"));
}

function setStatus(text) {
  if (el.statusText) el.statusText.textContent = text;
}

function versionImageUrl(version) {
  if (!state.docId || !version || !version.preprocessed_version_id) return "";
  return `/api/documents/${encodeURIComponent(state.docId)}/versions/`
    + `${encodeURIComponent(version.preprocessed_version_id)}/preprocessed`;
}

function renderBlockMarkdown(markdown) {
  if (typeof hooks.renderMarkdown === "function") {
    try { return hooks.renderMarkdown(markdown || ""); } catch (_) { /* plain fallback */ }
  }
  if (window.marked) {
    try { return window.marked.parse(markdown || ""); } catch (_) { /* plain fallback */ }
  }
  return `<p>${esc(markdown || "")}</p>`;
}

/* ---------- version switcher (side panel) ---------- */

function paintVersionList(chain, selected) {
  if (el.versionInfo) {
    const count = (chain && chain.count) || 0;
    el.versionInfo.textContent = count > 1
      ? `第 ${count} 版（历史 ${count - 1} 版留存）`
      : (count === 1 ? "第 1 版" : "暂无版本");
  }
  if (el.versionList) {
    el.versionList.innerHTML = core.renderVersionListHtml(chain, {
      selectedVersionId: selected,
      latestVersionId: chain && chain.latest_version_id,
    });
  }
  if (el.versionReadonlyNote) {
    const chainVersions = (chain && chain.versions) || [];
    const picked = chainVersions.find((version) => version.version_id === selected);
    if (picked && picked.is_history && !picked.is_edit) {
      const latest = chain && chain.latest_version_id;
      el.versionReadonlyNote.innerHTML = `🔒 正在只读查看历史版本 `
        + `<code>${esc(picked.version_id)}</code>；编辑始终作用于最新版`
        + (latest ? `（<code>${esc(latest)}</code>）` : "")
        + `。 <button type="button" class="btn small" id="version-back-latest">回到最新版</button>`;
      el.versionReadonlyNote.classList.remove("hidden");
    } else {
      el.versionReadonlyNote.textContent = "";
      el.versionReadonlyNote.classList.add("hidden");
    }
  }
  wireVersionItems();
}

function wireVersionItems() {
  if (!el.versionList) return;
  el.versionList.querySelectorAll("button[data-version-id]").forEach((button) => {
    button.addEventListener("click", () => selectVersion(button.dataset.versionId));
  });
  const back = el.versionReadonlyNote && el.versionReadonlyNote.querySelector("#version-back-latest");
  if (back) back.addEventListener("click", () => selectVersion(null, { open: false }));
}

/* Fetch S2's version chain and paint the richer switcher.  Failures keep the
   U3-rendered base list intact (offline / chain endpoint unavailable). */
export async function renderVersionPanel(documentId) {
  if (!el.versionList) return;
  let chain = null;
  try {
    chain = await api(`/api/documents/${encodeURIComponent(documentId)}/versions`);
  } catch (_) {
    return;
  }
  if (!chain || state.docId !== documentId) return;   // stale response
  chainCache = { documentId, chain };
  if (selectedVersion) {
    const stillThere = (chain.versions || []).some((v) => v.version_id === selectedVersion);
    if (!stillThere) selectedVersion = null;
  }
  paintVersionList(chain, selectedVersion);
}

/* Selecting a version opens the compare overlay read-only.  ``null`` returns
   to the latest (default latest vs previous). */
export function selectVersion(versionId, options = {}) {
  const chain = chainCache && chainCache.chain;
  if (versionId && chain && !(chain.versions || []).some((v) => v.version_id === versionId)) {
    return;
  }
  selectedVersion = versionId || null;
  if (chain) paintVersionList(chain, selectedVersion);
  const open = options.open !== false;
  if (!open) {
    closeCompare();
    return;
  }
  if (!versionId) {
    openCompare();
    return;
  }
  const latest = chain && chain.latest_version_id;
  if (versionId === latest) openCompare({ a: "prev", b: "latest" });
  else openCompare({ a: versionId, b: latest || "latest" });
}

/* ---------- comparison overlay ---------- */

function fillSelectors(chain, options) {
  const versions = (chain && chain.versions) || [];
  const optionsHtml = versions.map((version) => {
    const badge = version.is_edit ? "（当前编辑）"
      : (version.version_id === chain.latest_version_id ? "（当前版本）" : "");
    return `<option value="${esc(version.version_id)}">${esc(version.created_at || version.version_id)}`
      + ` · ${esc(version.source_label || version.source || "")}${badge}</option>`;
  }).join("");
  const set = (node, value) => {
    if (!node) return;
    node.innerHTML = optionsHtml;
    if (value != null) node.value = value;
  };
  const fallbackA = versions.length >= 2 ? versions[versions.length - 2].version_id : (versions[0] || {}).version_id;
  const fallbackB = chain.latest_version_id || (versions[versions.length - 1] || {}).version_id;
  set(el.diffSelectA, options.a != null ? options.a : fallbackA);
  set(el.diffSelectB, options.b != null ? options.b : fallbackB);
}

export async function openCompare(options = {}) {
  if (!state.docId || !el.diffView) return;
  if (!chainCache || chainCache.documentId !== state.docId) {
    try {
      const chain = await api(`/api/documents/${encodeURIComponent(state.docId)}/versions`);
      chainCache = { documentId: state.docId, chain };
      paintVersionList(chain, selectedVersion);
    } catch (e) {
      showToast("读取版本链失败：" + e.message, "err");
      return;
    }
  }
  fillSelectors(chainCache.chain, options);
  el.diffView.classList.remove("hidden");
  el.diffView.setAttribute("aria-hidden", "false");
  if (el.diffEmpty) el.diffEmpty.classList.add("hidden");
  await refreshCompare();
}

export function closeCompare() {
  if (!el.diffView) return;
  el.diffView.classList.add("hidden");
  el.diffView.setAttribute("aria-hidden", "true");
}

export function swapVersions() {
  if (!el.diffSelectA || !el.diffSelectB) return;
  const a = el.diffSelectA.value;
  el.diffSelectA.value = el.diffSelectB.value;
  el.diffSelectB.value = a;
  void refreshCompare();
}

export async function refreshCompare() {
  if (!state.docId) return;
  const a = el.diffSelectA ? el.diffSelectA.value : "prev";
  const b = el.diffSelectB ? el.diffSelectB.value : "latest";
  try {
    const payload = await api(
      `/api/documents/${encodeURIComponent(state.docId)}/diff`
      + `?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
    renderCompare(payload);
  } catch (e) {
    showToast("对比失败：" + e.message, "err");
    if (el.diffSummary) el.diffSummary.innerHTML = `<span class="dim">对比失败：${esc(e.message)}</span>`;
  }
}

function latestSide(payload) {
  if (payload.b && payload.b.is_current) return "b";
  if (payload.a && payload.a.is_current) return "a";
  return "b";
}

export function renderCompare(payload) {
  currentPayload = payload;
  if (!payload) return;
  if (el.diffSummary) el.diffSummary.innerHTML = core.renderSummaryBar(payload);
  if (el.diffReadonly) {
    const notice = core.renderReadOnlyNotice(payload);
    el.diffReadonly.innerHTML = notice;
    el.diffReadonly.classList.toggle("hidden", !notice);
  }
  if (el.diffEmpty) {
    if (!payload.a || !payload.b) {
      el.diffEmpty.textContent = "暂无版本记录，无法对比。";
      el.diffEmpty.classList.remove("hidden");
    } else if (payload.single_version) {
      el.diffEmpty.textContent = "只有 1 个版本，暂无可对比的历史版本；重新解析或保存编辑后会形成新版本。";
      el.diffEmpty.classList.remove("hidden");
    } else if (payload.empty) {
      el.diffEmpty.textContent = "两版内容一致，无块级变更（安全空 diff）。";
      el.diffEmpty.classList.remove("hidden");
    } else {
      el.diffEmpty.textContent = "";
      el.diffEmpty.classList.add("hidden");
    }
  }

  const side = latestSide(payload);
  if (el.diffHeadA) {
    el.diffHeadA.innerHTML = core.renderVersionHeadHtml(payload.a, "a", { imageUrl: versionImageUrl(payload.a) });
    el.diffHeadA.classList.toggle("diff-current", Boolean(payload.a && payload.a.is_current));
  }
  if (el.diffHeadB) {
    el.diffHeadB.innerHTML = core.renderVersionHeadHtml(payload.b, "b", { imageUrl: versionImageUrl(payload.b) });
    el.diffHeadB.classList.toggle("diff-current", Boolean(payload.b && payload.b.is_current));
  }
  if (el.diffRows) {
    el.diffRows.innerHTML = core.renderRowsHtml(payload, {
      latestSide: side,
      renderMarkdown: renderBlockMarkdown,
    });
    wireBlockClicks();
  }
  wireImageClicks();
}

function wireBlockClicks() {
  if (!el.diffRows) return;
  el.diffRows.querySelectorAll("[data-diff-block]").forEach((cell) => {
    const handler = () => locateBlock(cell.dataset.locate != null
      ? Number(cell.dataset.locate) : Number(cell.dataset.diffBlock));
    cell.addEventListener("click", handler);
    cell.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handler();
      }
    });
  });
}

function wireImageClicks() {
  if (!el.diffView) return;
  el.diffView.querySelectorAll(".diff-version-img").forEach((img) => {
    img.addEventListener("click", () => {
      if (typeof hooks.openImageViewer === "function") {
        hooks.openImageViewer(img.dataset.viewerSrc || img.src);
      }
    });
  });
}

/* Click-to-locate (AC4): scroll the *current* version column to the block that
   corresponds to a changed block.  A block removed in the current version has no
   target, so the row is flagged instead with an explicit explanation. */
export function locateBlock(index) {
  if (!el.diffRows || index == null || Number.isNaN(index)) return null;
  el.diffRows.querySelectorAll(".locate-flash").forEach((node) => node.classList.remove("locate-flash"));
  const target = el.diffRows.querySelector(`[data-block-index="${index}"].diff-latest`);
  if (target) {
    target.classList.add("locate-flash");
    if (typeof target.scrollIntoView === "function") {
      try { target.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (_) { /* jsdom-less */ }
    }
    setStatus(`已定位到当前版本第 ${index} 块（block-${index}，只读）`);
    return target;
  }
  const row = el.diffRows.querySelector(`[data-locate="${index}"]`);
  if (row) row.classList.add("locate-flash");
  setStatus(`当前版本中不存在第 ${index} 块（该块在当前版本已删除）`);
  return null;
}

/* Esc closes the compare overlay (wired from document.js's shortcut handler). */
export function handleVersionDiffShortcut(event) {
  if (event.key !== "Escape") return false;
  if (!isCompareOpen()) return false;
  event.preventDefault();
  closeCompare();
  return true;
}

/* ---------- wiring ---------- */

if (el.versionCompare) el.versionCompare.addEventListener("click", () => openCompare());
if (el.diffClose) el.diffClose.addEventListener("click", closeCompare);
if (el.diffSwap) el.diffSwap.addEventListener("click", swapVersions);
if (el.diffCompare) el.diffCompare.addEventListener("click", () => void refreshCompare());
if (el.diffSelectA) el.diffSelectA.addEventListener("change", () => void refreshCompare());
if (el.diffSelectB) el.diffSelectB.addEventListener("change", () => void refreshCompare());
if (el.diffBackLatest) {
  el.diffBackLatest.addEventListener("click", () => selectVersion(null, { open: true }));
}
