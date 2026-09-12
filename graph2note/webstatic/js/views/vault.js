/* graph2note — one-way Obsidian Vault export (U1 relocation, behaviour kept). */
"use strict";

import { el } from "../state.js";
import { api } from "../api.js";
import { esc, POLL_MS } from "../utils.js";
import { registerView } from "../router.js";
import { showToast } from "../ui.js";

let vaultPollTimer = null;
let vaultExportTaskId = null;

const VAULT_REPORT_LABELS = {
  added: "新增", updated: "更新", deleted: "删除", unchanged: "无变化",
  conflicts: "冲突", kept_user: "保留的用户文件", user_files: "用户文件",
};

function vaultCounts(report) {
  if (!report) return "";
  return Object.keys(VAULT_REPORT_LABELS).filter((key) =>
    Array.isArray(report[key]) && report[key].length
  ).map((key) => `${VAULT_REPORT_LABELS[key]} ${report[key].length}`).join(" · ");
}

function showVaultStatus(text, detail) {
  el.vaultExportStatus.innerHTML = "";
  const line = document.createElement("div");
  line.textContent = text;
  el.vaultExportStatus.appendChild(line);
  if (detail) {
    const d = document.createElement("div");
    d.className = "dim";
    d.textContent = detail;
    el.vaultExportStatus.appendChild(d);
  }
}

function vaultFileList(title, items) {
  if (!items || !items.length) return "";
  const lis = items.map((item) =>
    `<li>${esc(typeof item === "string" ? item : (item.managed || item.backup || ""))}</li>`).join("");
  return `<details class="vault-files"><summary>${esc(title)}（${items.length}）</summary><ul>${lis}</ul></details>`;
}

function vaultConflictsHtml(conflicts) {
  if (!conflicts || !conflicts.length) return "";
  const rows = conflicts.map((c) => `
    <li>
      <div>受管输出：<code>${esc(c.managed)}</code></div>
      <div class="dim">您的版本已保留为备份：<code>${esc(c.backup)}</code></div>
    </li>`).join("");
  return `<div class="vault-conflicts"><strong>检测到冲突：您手工修改过的文件未被覆盖，已保留为备份并同时生成系统版本（未自动合并）。请在 Obsidian 中核对两份内容。</strong><ul>${rows}</ul></div>`;
}

function renderVaultResult(st) {
  el.vaultExportStatus.classList.remove("ok", "err");
  el.vaultExportStatus.innerHTML = "";
  if (st.status === "done") {
    const r = st.report || {};
    el.vaultExportStatus.classList.add("ok");
    const head = document.createElement("div");
    head.textContent = `导出完成：${st.exported_documents} 份文档 → ${st.vault_root}`;
    el.vaultExportStatus.appendChild(head);
    const meta = document.createElement("div");
    meta.className = "dim";
    meta.textContent = (st.task_id ? `任务 ${st.task_id} · ` : "") + (vaultCounts(r) || "无变化");
    el.vaultExportStatus.appendChild(meta);
    el.vaultExportStatus.insertAdjacentHTML("beforeend",
      vaultConflictsHtml(r.conflicts) +
      vaultFileList("新增文件", r.added) +
      vaultFileList("更新文件", r.updated) +
      vaultFileList("删除文件", r.deleted) +
      vaultFileList("无变化文件", r.unchanged) +
      vaultFileList("保留的用户文件", r.kept_user) +
      vaultFileList("Vault 中的用户文件", r.user_files));
    showToast("已导出 Obsidian Vault", "ok");
  } else if (st.status === "failed") {
    el.vaultExportStatus.classList.add("err");
    const head = document.createElement("div");
    head.textContent = st.partial ? "导出失败（部分文件已写入，请核对 Vault）" : "导出失败";
    el.vaultExportStatus.appendChild(head);
    const err = document.createElement("div");
    err.className = "dim";
    err.textContent = st.error || "未知错误";
    el.vaultExportStatus.appendChild(err);
    showToast("导出失败：" + (st.error || ""), "err");
  }
}

function scheduleVaultPoll() {
  clearInterval(vaultPollTimer);
  const myTask = vaultExportTaskId;
  vaultPollTimer = setInterval(async () => {
    let st;
    try { st = await api("/api/vault/export"); }
    catch (e) { clearInterval(vaultPollTimer); return; }
    if (st.status === "running") return;
    if (myTask && st.task_id && st.task_id !== myTask) return;  // don't mix reports
    clearInterval(vaultPollTimer);
    renderVaultResult(st);
  }, POLL_MS);
}

async function renderVaultExport() {
  el.vaultExportZone.classList.remove("hidden");
  try {
    const st = await api("/api/vault/export");
    if (st && st.status === "running") {
      vaultExportTaskId = st.task_id || null;
      showVaultStatus("导出进行中…", st.target_dir || "");
      scheduleVaultPoll();
    } else if (st && (st.status === "done" || st.status === "failed")) {
      renderVaultResult(st);
    }
  } catch (e) { /* idle state is fine */ }
}

export async function startVaultExport() {
  const dir = el.vaultExportDir.value.trim();
  if (!dir) { showToast("请填写目标目录路径", "err"); return; }
  el.btnVaultExport.disabled = true;
  showVaultStatus("正在导出…", dir);
  try {
    const r = await api("/api/vault/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_dir: dir }),
    });
    if (r.status === "empty") {
      showVaultStatus("文档库为空，没有可导出的文档。", "");
    } else {
      vaultExportTaskId = r.task_id || null;
      scheduleVaultPoll();
    }
  } catch (e) {
    el.vaultExportStatus.classList.add("err");
    showVaultStatus("导出失败", e.message);
  } finally {
    el.btnVaultExport.disabled = false;
  }
}

el.vaultExportForm.addEventListener("submit", (event) => {
  event.preventDefault();
  startVaultExport();
});

registerView("vault-export", renderVaultExport);
