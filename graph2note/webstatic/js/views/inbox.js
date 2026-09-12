/* graph2note — read-only Inbox projection (U1 relocation).
   Issue 03 adds the "可合并" continuity queue: read-only detection from
   `/api/continuity/candidates`, per-item confirm/reject, and a post-merge
   hand-off to the S3 version switcher (which shows the `merge` event). */
"use strict";

import { el } from "../state.js";
import { api } from "../api.js";
import { esc, displayTime } from "../utils.js";
import { go, registerView } from "../router.js";
import { showViewError, clearViewError, showToast } from "../ui.js";
import {
  MERGE_REASON_LABEL,
  candidateByKey,
  mergeEmptyHtml,
  mergeListHtml,
  mergeResultHtml,
  pendingMergeCandidates,
} from "../inbox_merge_core.js";

let mergeCandidates = [];

function inboxItemHtml(item) {
  const reasons = (item.inbox_reason_labels || []).map((reason) =>
    `<span class="inbox-reason">${esc(reason)}</span>`).join("");
  const topics = (item.topics || []).map((topic) =>
    `<span class="timeline-topic">${esc(topic)}</span>`).join("");
  const tags = (item.tags || []).map((tag) =>
    `<span class="document-tag">#${esc(tag)}</span>`).join("");
  const effective = item.effective_time && item.effective_time.value
    ? displayTime(item.effective_time.value) : "无有效日期";
  return `<button class="inbox-item" type="button" data-route="${esc(`#doc/${encodeURIComponent(item.document_id)}`)}">
    <span class="inbox-item-main">
      <span class="inbox-item-title">${esc(item.title)}</span>
      <span class="inbox-item-meta">${esc(effective)}${topics}${tags}</span>
    </span>
    <span class="inbox-reasons">${reasons}</span>
    <span class="inbox-item-arrow" aria-hidden="true">›</span>
  </button>`;
}

/* ---------- continuity merge queue (issue 03) ---------- */

function ensureMergeSection() {
  let section = document.getElementById("inbox-merge");
  if (section) return section;
  section = document.createElement("section");
  section.id = "inbox-merge";
  section.className = "inbox-merge";
  section.innerHTML = `
    <div class="inbox-merge-head">
      <h3>${esc(MERGE_REASON_LABEL)}</h3>
      <p class="dim">同 PDF 的连续页、首尾衔接的手稿可合并为一篇；原稿软归档、可恢复。</p>
    </div>
    <div id="inbox-merge-result" class="inbox-merge-result hidden"></div>
    <div id="inbox-merge-list" class="inbox-merge-list"></div>`;
  el.inboxZone.appendChild(section);
  return section;
}

async function renderMergeSection() {
  const section = ensureMergeSection();
  const list = section.querySelector("#inbox-merge-list");
  const result = section.querySelector("#inbox-merge-result");
  if (!list) return;
  list.innerHTML = `<span class="dim">检测中…</span>`;
  try {
    const payload = await api("/api/continuity/candidates");
    mergeCandidates = pendingMergeCandidates(payload);
    list.innerHTML = mergeCandidates.length
      ? mergeListHtml(mergeCandidates) : mergeEmptyHtml();
    list.querySelectorAll("button[data-merge-confirm]").forEach((button) => {
      button.addEventListener("click", () => { void confirmMerge(button.dataset.mergeConfirm); });
    });
    list.querySelectorAll("button[data-merge-reject]").forEach((button) => {
      button.addEventListener("click", () => { void rejectMerge(button.dataset.mergeReject); });
    });
    if (result) result.classList.add("hidden");
  } catch (e) {
    mergeCandidates = [];
    list.innerHTML = mergeEmptyHtml("检测失败，请稍后重试。");
  }
}

async function confirmMerge(key) {
  const candidate = candidateByKey(mergeCandidates, key);
  if (!candidate) return;
  const label = `${candidate.titles ? candidate.titles[0] : candidate.document_id} + `
    + `${candidate.titles ? candidate.titles[1] : candidate.target_id}`;
  if (!window.confirm(`确认合并「${label}」？原两篇将软归档，可恢复。`)) return;
  try {
    const report = await api("/api/continuity/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: candidate.document_id,
        target_id: candidate.target_id,
      }),
    });
    showToast(`已合并为「${report.title}」`);
    await renderMergeSection();
    const section = document.getElementById("inbox-merge");
    const result = section && section.querySelector("#inbox-merge-result");
    if (result) {
      result.innerHTML = mergeResultHtml(report);
      result.classList.remove("hidden");
    }
    // Hand off to the merged document's version chain (S3 switcher shows the
    // `merge` source event + the two source documents in its detail).
    go(`#doc/${encodeURIComponent(report.merged_document_id)}/versions`);
  } catch (e) {
    showToast("合并失败：" + e.message, "err");
  }
}

async function rejectMerge(key) {
  const candidate = candidateByKey(mergeCandidates, key);
  if (!candidate) return;
  try {
    await api("/api/continuity/reject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: candidate.document_id,
        target_id: candidate.target_id,
        distance: candidate.phash_distance,
      }),
    });
    showToast("已拒绝，不再重复提示该配对。");
    await renderInbox();
  } catch (e) {
    showToast("拒绝失败：" + e.message, "err");
  }
}

async function renderInbox() {
  clearViewError(el.inboxZone);
  el.inboxZone.classList.remove("hidden");
  el.inboxList.innerHTML = "";
  el.inboxEmpty.classList.add("hidden");
  ensureMergeSection();
  try {
    const items = await api("/api/inbox");
    if (!items.length) {
      el.inboxEmpty.classList.remove("hidden");
    } else {
      el.inboxList.innerHTML = items.map(inboxItemHtml).join("");
      el.inboxList.querySelectorAll("button.inbox-item[data-route]").forEach((button) => {
        button.addEventListener("click", () => go(button.dataset.route));
      });
    }
  } catch (e) {
    el.inboxEmpty.classList.add("hidden");
    showViewError(el.inboxZone, "待整理列表加载失败：" + e.message, renderInbox);
  }
  await renderMergeSection();
}

registerView("inbox", renderInbox);
