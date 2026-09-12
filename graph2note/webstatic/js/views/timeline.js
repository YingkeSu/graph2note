/* graph2note — read-only timeline projection (moved verbatim under U1 shell). */
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { go, registerView } from "../router.js";
import { showToast } from "../ui.js";

// canonical default entry used by the sidebar nav and the group switcher
export const TIMELINE_DEFAULT_ROUTE = "#timeline/day";

function timelineItemHtml(item) {
  const effective = item.effective_time || {};
  const topics = (item.topics || []).map((topic) => `<span class="timeline-topic">${esc(topic)}</span>`).join("");
  const collections = (item.collections || []).map((collection) => `<span class="timeline-collection">${esc(collection)}</span>`).join("");
  return `<button class="timeline-item" type="button" data-route="${esc(item.route)}">
    <span class="timeline-item-date">${esc(item.date || "无日期")}</span>
    <span class="timeline-item-main">
      <span class="timeline-item-title">${esc(item.title)}</span>
      <span class="timeline-item-meta">${esc(effective.source || "无有效时间")}${topics}${collections}</span>
    </span>
    <span class="timeline-item-arrow" aria-hidden="true">›</span>
  </button>`;
}

function timelineGroupHtml(group) {
  const aggregates = (group.topic_aggregates || []).map((item) =>
    `<span class="timeline-summary-chip">${esc(item.topic)} · ${item.count}</span>`).join("");
  const runs = (group.adjacent_topic_runs || []).filter((run) => run.count > 1).map((run) =>
    `<span class="timeline-run-chip">${esc(run.topic)} 连续 ${run.count} 份</span>`).join("");
  return `<section class="timeline-group">
    <div class="timeline-group-head">
      <div>
        <h3>${esc(group.label)}</h3>
        <span class="dim">${group.count} 份 · ${esc(group.start_date)}${group.end_date !== group.start_date ? ` 至 ${esc(group.end_date)}` : ""}</span>
      </div>
      <div class="timeline-summary">${aggregates || `<span class="dim">暂无主题</span>`}</div>
    </div>
    ${runs ? `<div class="timeline-runs"><span class="dim">相邻主题</span>${runs}</div>` : ""}
    <div class="timeline-items">${group.items.map(timelineItemHtml).join("")}</div>
  </section>`;
}

function wireTimelineLinks(root) {
  root.querySelectorAll("button.timeline-item[data-route]").forEach((button) => {
    button.addEventListener("click", () => go(button.dataset.route));
  });
}

async function renderTimeline(groupBy) {
  el.timelineZone.classList.remove("hidden");
  el.timelineGroup.value = groupBy;
  el.timelineGroups.innerHTML = "";
  el.timelineUndatedItems.innerHTML = "";
  el.timelineUndated.classList.add("hidden");
  el.timelineEmpty.classList.add("hidden");
  try {
    const timeline = await api(`/api/timeline?group_by=${encodeURIComponent(groupBy)}`);
    const total = Number(timeline.total || 0);
    if (!total) {
      el.timelineEmpty.classList.remove("hidden");
    } else {
      el.timelineGroups.innerHTML = (timeline.groups || []).map(timelineGroupHtml).join("");
      wireTimelineLinks(el.timelineGroups);
    }
    const undated = timeline.undated || [];
    if (undated.length) {
      el.timelineUndated.classList.remove("hidden");
      el.timelineUndatedCount.textContent = `${undated.length} 份`;
      el.timelineUndatedItems.innerHTML = undated.map(timelineItemHtml).join("");
      wireTimelineLinks(el.timelineUndatedItems);
    }
  } catch (e) {
    el.timelineEmpty.classList.remove("hidden");
    el.timelineEmpty.querySelector("p").textContent = "时间轴加载失败。";
    showToast("加载时间轴失败：" + e.message, "err");
  }
}

function renderTimelineRoute(route) {
  state.timelineGroup = route.group;
  renderTimeline(route.group);
}

el.timelineGroup.addEventListener("change", () => go(`#timeline/${el.timelineGroup.value}`));

registerView("timeline", renderTimelineRoute);
