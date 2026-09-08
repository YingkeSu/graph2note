/* graph2note — upload → three-pane review/edit → copy/export. Zero build: plain JS. */
"use strict";

const $ = (s) => document.querySelector(s);
const POLL_MS = 1200;

const state = {
  jobId: null,
  status: "idle",
  doc: null,           // latest /api/jobs/{id} payload
  busy: false,         // a parse or action request is in flight (debounce)
  edited: "" ,          // current editor text we want to export
};

const el = {
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
  toast: $("#toast"),
  btnReparse: $("#btn-reparse"),
  btnCopy: $("#btn-copy"),
  btnDownload: $("#btn-download"),
  btnRepic: $("#btn-repic"),
  modelLabel: $("#model-label"),
};

/* ---------- helpers ---------- */

function showToast(msg, kind = "") {
  el.toast.textContent = msg;
  el.toast.className = "toast " + kind;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => el.toast.classList.add("hidden"), kind === "err" ? 6000 : 3000);
}

function api(route, opts = {}) {
  return fetch(route, opts).then(async (res) => {
    const ct = res.headers.get("content-type") || "";
    const body = ct.includes("json") ? await res.json() : await res.blob();
    if (!res.ok) throw new ApiError(res.status, body.detail || body.message || res.statusText);
    return body;
  });
}
class ApiError extends Error {}

/* ---------- views ---------- */

function showUpload() {
  el.uploadZone.classList.remove("hidden");
  el.workingZone.classList.add("hidden");
  el.workZone.classList.add("hidden");
}
function showWorking(text, detail) {
  el.uploadZone.classList.add("hidden");
  el.workZone.classList.add("hidden");
  el.workingZone.classList.remove("hidden");
  el.workingText.textContent = text;
  el.workingDetail.textContent = detail || "";
}
function showWork(doc) {
  el.uploadZone.classList.add("hidden");
  el.workingZone.classList.add("hidden");
  el.workZone.classList.remove("hidden");
}

/* ---------- upload ---------- */

function acceptFile(file) {
  if (!file) return;
  const isImg = /\.(jpe?g|png)$/i.test(file.name);
  if (!isImg) { el.uploadHint.textContent = "不支持的文件类型：请上传 JPG / JPEG / PNG。"; return; }
  if (file.size > 10 * 1024 * 1024) {
    el.uploadHint.textContent = `文件 ${(file.size / 1048576).toFixed(1)}MB 超过 10MB 上限，请压缩后再上传。`;
    return;
  }
  el.uploadHint.textContent = "";
  startUpload(file);
}

async function startUpload(file) {
  if (state.busy) return;
  state.busy = true;
  showWorking("正在上传…", file.name);
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await api("/api/parse", { method: "POST", body: fd });
    state.jobId = r.job_id;
    pollJob();
  } catch (e) {
    state.busy = false;
    showUpload();
    if (e instanceof ApiError) el.uploadHint.textContent = e.message;
    else el.uploadHint.textContent = "上传失败：" + e.message;
  }
}

/* ---------- poll & render ---------- */

function pollJob() {
  showWorking("解析中…", "正在预处理 → 识别 → 渲染，请稍候");
  const tick = async () => {
    let doc;
    try { doc = await api(`/api/jobs/${state.jobId}`); }
    catch (e) { showUpload(); el.uploadHint.textContent = "查询任务失败：" + e.message; state.busy = false; return; }
    state.doc = doc;

    if (doc.status === "queued" || doc.status === "processing") {
      setTimeout(tick, POLL_MS);
      return;
    }
    if (doc.status === "done") {
      state.busy = false;
      showWork(doc);
      renderWork(doc);
      return;
    }
    // failed / timeout
    state.busy = false;
    showFailed(doc);
  };
  tick();
}

function renderWork(doc) {
  el.modelLabel.textContent = "模型：" + (doc.model || "");
  setImage(doc);
  el.mdEditor.value = doc.markdown || "";
  el.mdEditor.disabled = false;
  state.edited = doc.markdown || "";
  renderPreview(doc.markdown || "");
  el.statusText.textContent =
    doc.empty ? "空文档：未识别出可渲染内容（预览与下载仍可用）。" : "解析完成 ✓";
  el.warnings.textContent = (doc.warnings || []).join("；");
  // placeholders (issue 09/10) revealed when data exists
  $("#marker-cv").classList.toggle("hidden", true);
  $("#marker-page").classList.toggle("hidden", true);
  setBusy(false);
}

function setImage(doc) {
  el.originalImg.src = `/api/jobs/${doc.job_id}/preprocessed`;
  el.originalImg.onerror = () => {
    // fall back to the original (preprocessed may lag on some paths)
    el.originalImg.src = `/api/jobs/${doc.job_id}/original`;
  };
}

function showFailed(doc) {
  showUpload();
  const reason = doc.error || (doc.error_kind === "timeout" ? "解析超时" : "解析失败");
  el.uploadHint.textContent = reason + "，原图已暂存，点击上方「重试解析」可直接重试。";
  showToast(reason, "err");
  el.uploadCard.dataset.retry = doc.job_id;
  el.uploadCard.querySelector(".upload-title").textContent = "解析未成功 — 可重试";
  addRetryButton(doc);
}

function addRetryButton(doc) {
  let btn = $("#btn-retry");
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "btn-retry";
    btn.className = "btn primary";
    btn.textContent = "重试解析";
    const wrap = document.createElement("p");
    wrap.className = "upload-sub";
    wrap.appendChild(btn);
    el.uploadCard.appendChild(wrap);
  }
  btn.onclick = async () => {
    el.uploadHint.textContent = "";
    state.jobId = doc.job_id;
    state.busy = true;
    showWorking("正在重新解析…", "复用原图，无需重新上传");
    try { await api(`/api/jobs/${doc.job_id}/reparse`, { method: "POST" }); pollJob(); }
    catch (e) { state.busy = false; showUpload(); el.uploadHint.textContent = "重试失败：" + e.message; }
  };
}

function setBusy(b) {
  state.busy = b;
  el.btnReparse.disabled = b;
  el.btnCopy.disabled = b;
  el.btnDownload.disabled = b;
}

/* ---------- live preview (editor -> render) ---------- */

function renderPreview(md) {
  const out = el.preview;
  out.innerHTML = "";
  try {
    if (!window.marked && window.__mdMissing) {
      out.innerHTML = `<div class="preview-error">⚠ 预览库（marked）未能加载，无法渲染；编辑不受影响。</div>`;
      return;
    }
    if (!window.marked) {
      // marked not yet loaded (defer-loaded); show plain text until ready
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
    // preview failure only affects the preview pane
    out.innerHTML = `<div class="preview-error">⚠ 预览渲染失败：${esc(e.message)}</div>`;
  }
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

let debounceId = null;
el.mdEditor.addEventListener("input", () => {
  state.edited = el.mdEditor.value;
  clearTimeout(debounceId);
  debounceId = setTimeout(() => renderPreview(state.edited), 180);
});

/* ---------- actions ---------- */

el.btnReparse.onclick = async () => {
  if (state.busy || !state.doc) return;
  const overwrite = window.confirm(
    "重新解析将用新的识别结果覆盖当前 Markdown（您的手写编辑将被替换）。确定继续吗？"
  );
  if (!overwrite) return;
  state.busy = true; setBusy(true);
  showWorking("重新解析中…", "复用原图");
  try {
    await api(`/api/jobs/${state.jobId}/reparse`, { method: "POST" });
    pollJob();
  } catch (e) {
    setBusy(false);
    showToast("重新解析失败：" + e.message, "err");
    renderWork(state.doc); // restore work pane
  }
};

el.btnCopy.onclick = async () => {
  const text = state.edited || el.mdEditor.value;
  try {
    await navigator.clipboard.writeText(text);
    showToast("已复制 Markdown 到剪贴板", "ok");
  } catch (e) {
    // fallback
    el.mdEditor.select();
    document.execCommand("copy");
    showToast("已复制（回退方式）", "ok");
  }
};

el.btnDownload.onclick = async () => {
  if (state.busy || !state.doc) return;
  state.busy = true; setBusy(true);
  try {
    const zip = await api(`/api/jobs/${state.jobId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: state.edited || el.mdEditor.value }),
    });
    const url = URL.createObjectURL(zip);
    const a = document.createElement("a");
    a.href = url;
    a.download = (state.doc.doc_id || "note") + ".zip";
    a.click();
    URL.revokeObjectURL(url);
    showToast("已下载 .md + 附件（zip）", "ok");
  } catch (e) {
    showToast("导出失败：" + e.message, "err");
  }
  setBusy(false);
};

el.btnRepic.onclick = () => setImage(state.doc);

/* ---------- wire upload ---------- */

el.pickFile.onclick = () => el.fileInput.click();
el.fileInput.addEventListener("change", (e) => acceptFile(e.target.files[0]));
["dragenter", "dragover"].forEach((ev) =>
  el.uploadCard.addEventListener(ev, (e) => {
    e.preventDefault(); el.uploadCard.classList.add("drag");
  })
);
["dragleave", "drop"].forEach((ev) =>
  el.uploadCard.addEventListener(ev, (e) => {
    e.preventDefault(); el.uploadCard.classList.remove("drag");
  })
);
el.uploadCard.addEventListener("drop", (e) => {
  const f = e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) acceptFile(f);
});