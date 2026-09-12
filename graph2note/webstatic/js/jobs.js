/* graph2note — parse-job working state + polling (U1).  Shared by the upload
   view (fresh parse) and the document view (reparse). */
"use strict";

import { el, state, hideAll, setBusy } from "./state.js";
import { api } from "./api.js";
import { POLL_MS } from "./utils.js";
import { showToast } from "./ui.js";
import { go } from "./router.js";

export function showWorking(text, detail) {
  hideAll();
  el.workingZone.classList.remove("hidden");
  el.workingText.textContent = text;
  el.workingDetail.textContent = detail || "";
}

export function pollJob(docId, thenRoute) {
  showWorking("解析中…", "正在预处理 → 识别 → 渲染，请稍候");
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    let job;
    try { job = await api(`/api/jobs/${state.jobId}`); }
    catch (e) {
      clearInterval(state.pollTimer);
      showToast("查询任务失败：" + e.message, "err");
      go("#library");
      return;
    }
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
