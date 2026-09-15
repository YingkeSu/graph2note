/* graph2note — image upload / fresh-parse entry (U1 relocation). */
"use strict";

import { el, state, setBusy } from "../state.js";
import { api } from "../api.js";
import { registerView, go } from "../router.js";
import { pollJob, showWorking } from "../jobs.js";
import { POLL_MS } from "../utils.js";
import { showToast } from "../ui.js";

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

registerView("upload", renderUpload);

/* ---------------------------------------------------------------------------
 * SPW I/P1 — paper PDF entry (append-only).
 *
 * A .pdf dropped on / picked from the same upload zone goes to the paper
 * import pipeline (`/api/papers/import`, text layer first, VLM fallback for
 * scans) instead of the image path.  Nothing above changes: the capture-phase
 * listeners only pre-empt the image handlers for PDF files, so JPG/PNG
 * behaviour is byte-for-byte the same.
 * ------------------------------------------------------------------------- */

const PAPER_POLL_MS = Math.max(POLL_MS || 1000, 800);
const PAPER_STATES = new Set(["done", "failed", "interrupted"]);

export function isPdfFile(file) {
  return !!file && /\.pdf$/i.test(file.name || "");
}

export function paperFileFromEvent(event) {
  if (event.type === "drop") {
    const files = event.dataTransfer && event.dataTransfer.files;
    return files && files[0];
  }
  const files = event.target && event.target.files;
  return files && files[0];
}

/* Pure decision the interceptor is built on: the event must originate on the
   upload zone (`change` on the hidden file input, `drop` on the card or one
   of its children) and carry a PDF. Images keep the unchanged image path.
   `zone` is injected so the offline DOM contract can pin the matrix without a
   browser. */
export function shouldInterceptPaperEvent(event, zone) {
  const onZone = event.type === "drop"
    ? (event.target === zone.uploadCard || zone.uploadCard.contains(event.target))
    : event.target === zone.fileInput;
  if (!onZone) return false;
  return isPdfFile(paperFileFromEvent(event));
}

export function interceptPaperFile(event) {
  const zone = { uploadCard: el.uploadCard, fileInput: el.fileInput };
  if (!shouldInterceptPaperEvent(event, zone)) return;
  event.preventDefault();
  event.stopPropagation();  // capture phase: the image handlers never see a PDF
  startPaperUpload(paperFileFromEvent(event));
}

async function startPaperUpload(file) {
  if (state.busy) return;
  state.busy = true; setBusy(true);
  showWorking("正在导入论文…", file.name + " · 文本层直提优先，扫描版自动回退 VLM");
  try {
    const form = new FormData();
    form.append("file", file);
    const job = await api("/api/papers/import", { method: "POST", body: form });
    pollPaper(job.paper_id);
  } catch (e) {
    state.busy = false; setBusy(false);
    renderUpload();
    el.uploadHint.textContent = "论文导入失败：" + e.message;
  }
}

function pollPaper(paperId) {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    let job;
    try {
      job = await api(`/api/papers/${encodeURIComponent(paperId)}`);
    } catch (e) {
      clearInterval(state.pollTimer);
      state.busy = false; setBusy(false);
      showToast("查询论文任务失败：" + e.message, "err");
      go("#library");
      return;
    }
    if (!PAPER_STATES.has(job.status)) return;
    clearInterval(state.pollTimer);
    state.busy = false; setBusy(false);
    if (job.status === "done" && job.document_id) {
      const via = job.source === "text-layer" ? "文本层直提" : "VLM 逐页（扫描版）";
      showToast(`论文导入完成：${via}，${job.sections} 个章节。`, "ok");
      go(`#doc/${encodeURIComponent(job.document_id)}`);
    } else {
      showToast((job.error || "论文导入失败") + "，可在重试后继续。", "err");
      go("#library");
    }
  }, PAPER_POLL_MS);
}

// Capture phase on the document: guaranteed to run before the zone's image
// listeners (which are registered earlier and on the target itself), so a PDF
// is intercepted while image events stay completely untouched.
document.addEventListener("change", interceptPaperFile, true);
document.addEventListener("drop", interceptPaperFile, true);
