/* graph2note — read-only timeline view (U5 visual upgrade).

   Renders the `/api/timeline` projection as a vertical trunk with ticks,
   thumbnails, source icons, tag counts, gap markers, adjacent-topic colour
   bands and a monthly density bar.  The view is strictly read-only: it only
   issues GET requests and never edits, reparses or deletes anything. */
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { go, registerView } from "../router.js";
import { showToast } from "../ui.js";
import {
  createThumbnailLoader,
  densityBarsHtml,
  loadTimeline,
  timelineGroupsHtml,
  timelineItemHtml,
  wireTimeline,
} from "../timeline_view.js";

// canonical default entry used by the sidebar nav and the group switcher
export const TIMELINE_DEFAULT_ROUTE = "#timeline/day";

let thumbnailLoader = null;

function installThumbnailLazyLoading(root) {
  if (thumbnailLoader) thumbnailLoader.disconnect();
  if (!root || !root.querySelectorAll) return;
  const images = [...root.querySelectorAll("img.timeline-thumb[data-src]")];
  if (!images.length) return;
  thumbnailLoader = createThumbnailLoader({
    makeObserver: typeof IntersectionObserver === "function"
      ? (callback) => new IntersectionObserver(callback, { rootMargin: "0px" })
      : undefined,
  });
  images.forEach((image) => thumbnailLoader.observe(image));
}

function scrollToGroup(groupKey) {
  if (!groupKey || !el.timelineGroups) return;
  const safe = String(groupKey).replace(/["\\]/g, "");
  const target = el.timelineGroups.querySelector(`.timeline-group[data-group-key="${safe}"]`);
  if (target && target.scrollIntoView) target.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function renderTimeline(groupBy) {
  el.timelineZone.classList.remove("hidden");
  el.timelineGroup.value = groupBy;
  el.timelineGroups.innerHTML = "";
  el.timelineUndatedItems.innerHTML = "";
  el.timelineUndated.classList.add("hidden");
  el.timelineEmpty.classList.add("hidden");
  if (el.timelineDensity) el.timelineDensity.innerHTML = "";
  try {
    const timeline = await loadTimeline(api, groupBy);
    const total = Number(timeline.total || 0);
    if (!total) {
      el.timelineEmpty.classList.remove("hidden");
    } else {
      el.timelineGroups.innerHTML = timelineGroupsHtml(timeline.groups, esc);
      wireTimeline(el.timelineGroups, { go, scrollTo: scrollToGroup });
    }
    if (el.timelineDensity) {
      el.timelineDensity.innerHTML = densityBarsHtml(timeline.density, timeline.density_max, esc);
      wireTimeline(el.timelineDensity, { scrollTo: scrollToGroup });
    }
    const undated = timeline.undated || [];
    if (undated.length) {
      el.timelineUndated.classList.remove("hidden");
      el.timelineUndatedCount.textContent = `${undated.length} 份`;
      el.timelineUndatedItems.innerHTML = undated.map((item, index) => timelineItemHtml(item, esc, { index })).join("");
      wireTimeline(el.timelineUndatedItems, { go });
    }
    installThumbnailLazyLoading(el.timelineZone);
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
