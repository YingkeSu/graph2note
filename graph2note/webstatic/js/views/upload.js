/* graph2note — image upload / fresh-parse entry (U1 relocation). */
"use strict";

import { el, state, setBusy } from "../state.js";
import { api } from "../api.js";
import { registerView } from "../router.js";
import { pollJob, showWorking } from "../jobs.js";

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
