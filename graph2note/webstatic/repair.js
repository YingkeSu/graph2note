/* graph2note — R1 black-image repair report (self-contained view).
 *
 * Kept out of app.js on purpose: it injects its own topbar entry, its own
 * zone and its own styles, so the global layout work (U1) can move app.js
 * without conflicts.  Interaction mirrors the PDF batch-job pattern: scan is
 * a read-only dry-run, "确认修复" posts explicit document ids + confirm=true,
 * then the view polls GET /api/repair/{id} until the run finishes.
 */
"use strict";

(function () {
  const POLL_MS = 1200;
  const STATUS_LABEL = {
    black: "黑图",
    suspected: "疑似空白",
    needs_reupload: "需重新上传",
    healthy: "正常",
  };

  const state = {
    report: null,
    job: null,
    pollTimer: null,
    busy: false,
  };

  function h(html) {
    const d = document.createElement("div");
    d.innerHTML = html;
    return d.firstElementChild;
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  async function api(route, opts) {
    const res = await fetch(route, opts || {});
    const ct = res.headers.get("content-type") || "";
    let body = {};
    try {
      body = ct.includes("json") ? await res.json() : await res.text();
    } catch (_) { /* keep body */ }
    if (!res.ok) {
      const msg = (body && body.detail) || res.statusText;
      const err = new Error(msg);
      err.status = res.status;
      throw err;
    }
    return body;
  }

  function injectStyles() {
    if (document.getElementById("repair-styles")) return;
    const style = document.createElement("style");
    style.id = "repair-styles";
    style.textContent = `
.repair-zone { max-width: 980px; margin: 0 auto; padding: 18px 22px 60px; }
.repair-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.repair-head h2 { margin: 0; }
.repair-summary { display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0; }
.repair-chip { border: 1px solid #d8dee6; border-radius: 999px; padding: 4px 12px;
  font-size: 13px; background: #fff; }
.repair-chip.black { border-color: #e5484d; color: #c62a2f; }
.repair-chip.suspected { border-color: #f0a33a; color: #b26b00; }
.repair-chip.needs_reupload { border-color: #9aa4b2; color: #5b6472; }
.repair-chip.healthy { border-color: #3fbf6f; color: #1f8a4c; }
.repair-budget { font-weight: 600; margin-left: auto; }
.repair-actions { display: flex; gap: 10px; margin: 10px 0 16px; }
.repair-list { display: flex; flex-direction: column; gap: 8px; }
.repair-row { display: grid; grid-template-columns: 1fr auto auto auto;
  gap: 12px; align-items: center; border: 1px solid #e4e9ef; border-radius: 8px;
  padding: 10px 12px; background: #fff; }
.repair-row .doc { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px; }
.repair-badge { font-size: 12px; padding: 2px 8px; border-radius: 6px;
  background: #eef2f6; }
.repair-badge.black { background: #fde8e8; color: #b3261e; }
.repair-badge.suspected { background: #fdf1dd; color: #8a5a00; }
.repair-badge.needs_reupload { background: #eef2f6; color: #4a5563; }
.repair-badge.healthy { background: #e6f6ec; color: #1f7a45; }
.repair-badge.success { background: #e6f6ec; color: #1f7a45; }
.repair-badge.failed { background: #fde8e8; color: #b3261e; }
.repair-badge.skipped, .repair-badge.pending, .repair-badge.processing {
  background: #eef2f6; color: #4a5563; }
.repair-dim { color: #6b7480; font-size: 12px; }
.repair-progress { margin-top: 14px; }
.repair-note { color: #6b7480; font-size: 13px; }
`;
    document.head.appendChild(style);
  }

  function ensureDom() {
    injectStyles();
    const topbar = document.querySelector(".topbar");
    if (topbar && !document.getElementById("nav-repair")) {
      const btn = h(`<button class="btn small" id="nav-repair" title="黑图修复报告">修复报告</button>`);
      const upload = document.getElementById("nav-upload");
      topbar.insertBefore(btn, upload || null);
      btn.addEventListener("click", () => { location.hash = "#repair"; });
    }
    if (!document.getElementById("repair-zone")) {
      const zone = h(`
<section id="repair-zone" class="repair-zone hidden">
  <div class="repair-head">
    <h2>黑图修复报告</h2>
    <span class="repair-dim">检测历史版本中因透视 bug 产出纯黑 preprocessed.png 的文档，并从 preprocessed_raw.png 重跑为新版本（不覆盖旧版本）。</span>
  </div>
  <div id="repair-summary" class="repair-summary"></div>
  <div class="repair-actions">
    <button id="repair-scan-btn" class="btn small">重新检测</button>
    <button id="repair-run-btn" class="btn primary" disabled>确认并开始修复</button>
    <button id="repair-retry-btn" class="btn small hidden">重试未通过</button>
  </div>
  <div id="repair-note" class="repair-note"></div>
  <div id="repair-list" class="repair-list"></div>
</section>`);
      document.body.insertBefore(zone, document.getElementById("toast"));
      document.getElementById("repair-scan-btn").addEventListener("click", () => scan());
      document.getElementById("repair-run-btn").addEventListener("click", () => runRepair());
      document.getElementById("repair-retry-btn").addEventListener("click", () => retryRepair());
    }
  }

  function active() {
    return (location.hash || "").replace(/^#\/?/, "") === "repair";
  }

  function showZone(on) {
    const zone = document.getElementById("repair-zone");
    if (!zone) return;
    if (on) {
      document.querySelectorAll("body > section").forEach((s) => {
        if (s.id !== "repair-zone") s.classList.add("hidden");
      });
      zone.classList.remove("hidden");
    } else {
      zone.classList.add("hidden");
    }
  }

  function chips(report) {
    const s = report.summary;
    return [
      `<span class="repair-chip black">黑图 ${s.black}</span>`,
      `<span class="repair-chip suspected">疑似空白 ${s.suspected}</span>`,
      `<span class="repair-chip needs_reupload">需重新上传 ${s.needs_reupload}</span>`,
      `<span class="repair-chip healthy">正常 ${s.healthy}</span>`,
      `<span class="repair-chip">页数 ${s.pages}</span>`,
      `<span class="repair-budget">预估 VLM 调用数 ${s.estimated_vlm_calls}</span>`,
    ].join("");
  }

  function renderReport() {
    const report = state.report;
    if (!report) return;
    document.getElementById("repair-summary").innerHTML = chips(report);
    const runBtn = document.getElementById("repair-run-btn");
    runBtn.disabled = !report.repairable.length || state.busy;
    runBtn.textContent = report.repairable.length
      ? `确认并开始修复（${report.repairable.length} 篇 / 预估 ${report.summary.estimated_vlm_calls} 次调用）`
      : "没有可修复的文档";
    document.getElementById("repair-note").textContent = report.repairable.length
      ? "点击确认后会真实调用解析模型；旧版本与 preprocessed_raw.png 不会被覆盖或删除。"
      : "当前没有黑图或疑似空白文档需要重跑。";

    const list = document.getElementById("repair-list");
    list.innerHTML = "";
    for (const d of report.documents) {
      if (d.status === "healthy" && report.repairable.length) continue;
      const mean = d.mean == null ? "—" : d.mean.toFixed(1);
      const ink = d.ink_ratio == null ? "—" : d.ink_ratio.toFixed(4);
      list.appendChild(h(`<div class="repair-row">
        <span class="doc">${esc(d.document_id)}</span>
        <span class="repair-dim">${esc(d.title || "")}</span>
        <span class="repair-dim">均值 ${mean} · 墨迹 ${ink} · 页数 ${d.pages}</span>
        <span class="repair-badge ${d.status}">${esc(d.status_label || STATUS_LABEL[d.status] || d.status)}</span>
      </div>`));
    }
  }

  function renderJob() {
    const job = state.job;
    if (!job) return;
    document.getElementById("repair-summary").innerHTML =
      `<span class="repair-chip">任务 ${esc(job.status)}</span>` +
      `<span class="repair-chip">成功 ${job.counts.success}</span>` +
      `<span class="repair-chip black">失败 ${job.counts.failed}</span>` +
      `<span class="repair-chip needs_reupload">跳过 ${job.counts.skipped}</span>` +
      `<span class="repair-budget">实际 VLM 调用 ${job.vlm_calls} / 预估 ${job.estimated_vlm_calls}</span>`;
    const retryBtn = document.getElementById("repair-retry-btn");
    const hasRetry = (job.retryable || []).length > 0;
    retryBtn.classList.toggle("hidden", !hasRetry);
    retryBtn.disabled = state.busy;

    const list = document.getElementById("repair-list");
    list.innerHTML = "";
    for (const item of job.items) {
      const post = item.post_mean == null ? "" :
        ` 均值 ${item.post_mean.toFixed(1)} · 墨迹 ${(item.post_ink || 0).toFixed(4)}`;
      const note = item.error || item.reason || "";
      list.appendChild(h(`<div class="repair-row">
        <span class="doc">${esc(item.document_id)}</span>
        <span class="repair-dim">${esc(note)}</span>
        <span class="repair-dim">${esc(post)}</span>
        <span class="repair-badge ${item.status}">${esc(item.status)}</span>
      </div>`));
    }
  }

  async function scan() {
    if (state.busy) return;
    state.busy = true;
    document.getElementById("repair-note").textContent = "正在检测…";
    try {
      state.report = await api("/api/repair/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      state.job = null;
      renderReport();
      document.getElementById("repair-retry-btn").classList.add("hidden");
    } catch (e) {
      document.getElementById("repair-note").textContent = "检测失败：" + e.message;
    } finally {
      state.busy = false;
      const runBtn = document.getElementById("repair-run-btn");
      if (state.report) runBtn.disabled = !state.report.repairable.length;
    }
  }

  async function runRepair() {
    if (state.busy || !state.report || !state.report.repairable.length) return;
    state.busy = true;
    document.getElementById("repair-run-btn").disabled = true;
    try {
      const started = await api("/api/repair/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document_ids: state.report.repairable,
          confirm: true,
        }),
      });
      document.getElementById("repair-note").textContent =
        "修复进行中，可离开本页；进度会自动刷新。";
      poll(started.repair_id);
    } catch (e) {
      document.getElementById("repair-note").textContent = "修复启动失败：" + e.message;
      state.busy = false;
    }
  }

  async function retryRepair() {
    if (state.busy || !state.job) return;
    state.busy = true;
    try {
      await api(`/api/repair/${state.job.repair_id}/retry`, { method: "POST" });
      document.getElementById("repair-note").textContent = "正在重试未通过的文档…";
      poll(state.job.repair_id);
    } catch (e) {
      document.getElementById("repair-note").textContent = "重试失败：" + e.message;
      state.busy = false;
    }
  }

  function poll(repairId) {
    clearTimeout(state.pollTimer);
    state.busy = true;
    const tick = async () => {
      try {
        state.job = await api(`/api/repair/${repairId}`);
        renderJob();
        if (state.job.status === "queued" || state.job.status === "processing") {
          state.pollTimer = setTimeout(tick, POLL_MS);
          return;
        }
        state.busy = false;
        document.getElementById("repair-note").textContent = state.job.status === "done"
          ? "修复完成；结果已落盘，可在下方逐篇查看。"
          : "修复结束但仍有未通过项，可点击「重试未通过」。";
        await scan();  // refresh the report so the counts reflect the repair
        renderJob();   // keep the per-document results visible after refresh
      } catch (e) {
        state.busy = false;
        document.getElementById("repair-note").textContent = "进度查询失败：" + e.message;
      }
    };
    tick();
  }

  function onRoute() {
    ensureDom();
    if (active()) {
      showZone(true);
      if (!state.report && !state.job) scan();
      else if (state.job) renderJob();
      else renderReport();
    } else {
      showZone(false);
    }
  }

  window.addEventListener("hashchange", onRoute);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onRoute);
  } else {
    onRoute();
  }
})();
