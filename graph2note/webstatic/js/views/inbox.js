/* graph2note — read-only Inbox projection (U1 relocation). */
"use strict";

import { el } from "../state.js";
import { api } from "../api.js";
import { esc, displayTime } from "../utils.js";
import { go, registerView } from "../router.js";
import { showToast } from "../ui.js";

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

async function renderInbox() {
  el.inboxZone.classList.remove("hidden");
  el.inboxList.innerHTML = "";
  el.inboxEmpty.classList.add("hidden");
  try {
    const items = await api("/api/inbox");
    if (!items.length) {
      el.inboxEmpty.classList.remove("hidden");
      return;
    }
    el.inboxList.innerHTML = items.map(inboxItemHtml).join("");
    el.inboxList.querySelectorAll("button.inbox-item[data-route]").forEach((button) => {
      button.addEventListener("click", () => go(button.dataset.route));
    });
  } catch (e) {
    el.inboxEmpty.classList.remove("hidden");
    el.inboxEmpty.querySelector("p").textContent = "Inbox 加载失败。";
    showToast("加载 Inbox 失败：" + e.message, "err");
  }
}

registerView("inbox", renderInbox);
