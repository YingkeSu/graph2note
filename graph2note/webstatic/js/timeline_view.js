/* graph2note — Timeline view-model, visual (trunk/ticks) markup, run bands and
   viewport-gated thumbnail loader (U5).

   Pure module: no imports and no DOM access at load time, so the Node contract
   test (tests/timeline_view.mjs) exercises the real markup, the adjacent-topic
   run band expand/collapse state, the lazy-loading gate and the read-only
   request surface without a browser.

   Read-only red line: this module only ever *builds* markup and reads the
   `/api/timeline` payload.  ``loadTimeline`` takes the injected ``api`` wrapper
   and issues exactly one GET; no write verbs exist here.
*/
"use strict";

export const TIMELINE_DEFAULT_ROUTE = "#timeline/day";

/* Stable palette for adjacent-topic runs; a topic always maps to one hue. */
export const RUN_COLORS = [
  "#4f7fe8", "#c07a1a", "#16836d", "#8b5cf6",
  "#d9466a", "#0ea5e9", "#65a30d", "#db7c26",
];

export function topicColor(topic) {
  const text = String(topic == null ? "" : topic);
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) % 1000003;
  }
  return RUN_COLORS[hash % RUN_COLORS.length];
}

/** Source icon/label derived from the API's `source_kind` (image/pdf/document). */
export function sourceIcon(item) {
  const kind = (item && item.source_kind) || ((item && item.source_pdf) ? "pdf" : "image");
  if (kind === "pdf") {
    return { kind: "pdf", icon: "📄", label: (item && item.source_label) || "PDF 页面" };
  }
  if (kind === "document") {
    return { kind: "document", icon: "📝", label: (item && item.source_label) || "文档" };
  }
  return { kind: "image", icon: "🖼", label: (item && item.source_label) || "图片上传" };
}

/** "间隔 12 天" marker between two non-touching groups (empty when adjacent). */
export function gapLabel(days) {
  const value = Number(days);
  if (!Number.isFinite(value) || value < 1) return "";
  return `间隔 ${value} 天`;
}

export function timelineItemVm(item) {
  const topics = Array.isArray(item && item.topics) ? item.topics.map(String) : [];
  const tags = Array.isArray(item && item.tags) ? item.tags : [];
  const count = item && Number.isFinite(item.tag_count) ? item.tag_count : tags.length;
  return {
    id: String((item && item.document_id) || ""),
    title: String((item && (item.title || item.document_id)) || "未命名文档"),
    date: item && item.date ? String(item.date) : "",
    route: String((item && item.route) || "#library"),
    topics,
    tagCount: count,
    source: sourceIcon(item),
    thumbnail: (item && item.thumbnail_url) || "",
  };
}

function escapeLike(fn) {
  if (typeof fn === "function") return fn;
  return (value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function runsFor(runs, documentId) {
  const indices = [];
  (runs || []).forEach((run, index) => {
    if (run && Array.isArray(run.document_ids) && run.document_ids.includes(documentId)) {
      indices.push(index);
    }
  });
  return indices;
}

/** One entry row: thumbnail / title / source icon / date / topic chips / tag count. */
export function timelineItemHtml(item, escape, options = {}) {
  const esc = escapeLike(escape);
  const vm = timelineItemVm(item);
  const index = Number.isFinite(options.index) ? options.index : 0;
  const runs = Array.isArray(options.runs) ? options.runs : [];
  const runIndices = runsFor(runs, vm.id);
  const rails = runIndices
    .map((i) => `<i class="timeline-run-rail" style="--run-color:${topicColor(runs[i].topic)}"></i>`)
    .join("");
  const thumb = vm.thumbnail
    ? `<img class="timeline-thumb" loading="lazy" decoding="async" alt="" data-src="${esc(vm.thumbnail)}" />`
    : `<span class="timeline-thumb timeline-thumb-missing" aria-hidden="true">◌</span>`;
  const topics = vm.topics
    .map((topic) => `<span class="timeline-topic" style="--run-color:${topicColor(topic)}">${esc(topic)}</span>`)
    .join("");
  const tagChip = vm.tagCount
    ? `<span class="timeline-tag-count" title="${esc(vm.tagCount)} 个标签"># 标签 ${esc(vm.tagCount)}</span>`
    : "";
  const date = vm.date
    ? `<time class="timeline-item-date" datetime="${esc(vm.date)}">${esc(vm.date)}</time>`
    : `<span class="timeline-item-date dim">无日期</span>`;
  return `<li class="timeline-item-row" data-item-index="${index}" data-run-indices="${runIndices.join(",")}">
      <span class="timeline-run-rails" aria-hidden="true">${rails}</span>
      <button class="timeline-item" type="button" data-route="${esc(vm.route)}">
        <span class="timeline-thumb-wrap">
          ${thumb}
          <span class="timeline-source" data-source-kind="${esc(vm.source.kind)}" title="${esc(vm.source.label)}" aria-label="${esc(vm.source.label)}">${vm.source.icon}</span>
        </span>
        <span class="timeline-item-main">
          <span class="timeline-item-title">${esc(vm.title)}</span>
          <span class="timeline-item-meta">${date}${topics}${tagChip}</span>
        </span>
        <span class="timeline-item-arrow" aria-hidden="true">›</span>
      </button>
    </li>`;
}

/** Run band buttons: adjacent-topic visual aggregation (expand/collapse). */
export function runBandsHtml(runs, escape) {
  const esc = escapeLike(escape);
  return (runs || []).map((run, index) => {
    const color = topicColor(run.topic);
    return `<button type="button" class="timeline-run-band" data-run-index="${index}" aria-expanded="false" style="--run-color:${color}" title="展开高亮「${esc(run.topic)}」的连续条目">
        <span class="timeline-run-swatch" aria-hidden="true"></span>
        <span class="timeline-run-topic">${esc(run.topic)}</span>
        <span class="timeline-run-count">连续 ${esc(run.count)} 份</span>
        <span class="timeline-run-toggle" aria-hidden="true">展开</span>
      </button>`;
  }).join("");
}

/** One dated group: tick on the trunk + card with runs and items. */
export function timelineGroupHtml(group, escape) {
  const esc = escapeLike(escape);
  const runs = (group.adjacent_topic_runs || []).filter((run) => run && run.count > 1);
  const aggregates = (group.topic_aggregates || [])
    .map((entry) => `<span class="timeline-summary-chip">${esc(entry.topic)} · ${esc(entry.count)}</span>`)
    .join("");
  const items = (group.items || [])
    .map((item, index) => timelineItemHtml(item, esc, { index, runs }))
    .join("");
  const range = group.start_date !== group.end_date
    ? `${group.start_date} 至 ${group.end_date}`
    : group.start_date;
  const gap = group.gap_days == null ? "" : ` data-gap-days="${esc(group.gap_days)}"`;
  return `<section class="timeline-group" data-group-key="${esc(group.key)}"${gap}>
      <span class="timeline-tick" aria-hidden="true"></span>
      <div class="timeline-group-body">
        <div class="timeline-group-head">
          <div class="timeline-tick-label">
            <h3>${esc(group.label)}</h3>
            <span class="dim">${esc(group.count)} 份 · ${esc(range)}</span>
          </div>
          <div class="timeline-summary">${aggregates || `<span class="dim">暂无主题</span>`}</div>
        </div>
        ${runs.length ? `<div class="timeline-runs">${runBandsHtml(runs, esc)}</div>` : ""}
        <ol class="timeline-items">${items}</ol>
      </div>
    </section>`;
}

/** All groups plus the "间隔 N 天" markers between non-touching ones. */
export function timelineGroupsHtml(groups, escape) {
  const esc = escapeLike(escape);
  let html = "";
  (groups || []).forEach((group, index) => {
    if (index > 0) {
      const label = gapLabel(group.gap_days);
      if (label) {
        html += `<div class="timeline-gap" data-gap-days="${esc(group.gap_days)}"><span class="timeline-gap-label">${esc(label)}</span></div>`;
      }
    }
    html += timelineGroupHtml(group, esc);
  });
  return html;
}

/** Mini density bar: documents per month, clickable to jump to the group. */
export function densityBarsHtml(density, densityMax, escape) {
  const esc = escapeLike(escape);
  const entries = Array.isArray(density) ? density : [];
  if (!entries.length) return "";
  const declared = Number(densityMax);
  const max = declared > 0 ? declared : Math.max(1, ...entries.map((entry) => Number(entry.count) || 0));
  return entries.map((entry) => {
    const count = Number(entry.count) || 0;
    const percent = Math.max(8, Math.round((count / max) * 100));
    const month = String(entry.month || "");
    const short = month.slice(5) || month;
    return `<button type="button" class="timeline-density-bar" data-group-key="${esc(entry.group_key || "")}" data-month="${esc(month)}" title="${esc(month)} · ${esc(count)} 份" aria-label="${esc(month)} 共 ${esc(count)} 份，点击跳转">
        <span class="timeline-density-fill" style="height:${percent}%"></span>
        <span class="timeline-density-label">${esc(short)}</span>
      </button>`;
  }).join("");
}

/* ------------------------------------------------------------------ */
/* Read-only data access                                               */
/* ------------------------------------------------------------------ */

/** The single read-only request the timeline ever makes (always GET). */
export function loadTimeline(api, groupBy) {
  const group = groupBy === "week" ? "week" : "day";
  return api(`/api/timeline?group_by=${encodeURIComponent(group)}`);
}

/* ------------------------------------------------------------------ */
/* Thumbnail lazy loading                                              */
/* ------------------------------------------------------------------ */

/** Viewport-gated loader: markup carries `data-src` only, so parsing the
    timeline issues no image request; `src` is assigned on intersection. */
export function createThumbnailLoader({ makeObserver, load } = {}) {
  const assign = typeof load === "function" ? load : (img) => {
    const src = img.getAttribute("data-src");
    if (src) img.setAttribute("src", src);
    img.removeAttribute("data-src");
  };
  if (typeof makeObserver !== "function") {
    return {
      observe(img) { if (img) assign(img); },
      disconnect() {},
    };
  }
  const observer = makeObserver((entries, obs) => {
    for (const entry of entries) {
      if (!entry || !entry.isIntersecting) continue;
      if (obs && obs.unobserve) obs.unobserve(entry.target);
      assign(entry.target);
    }
  });
  return {
    observe(img) { if (img && observer && observer.observe) observer.observe(img); },
    disconnect() { if (observer && observer.disconnect) observer.disconnect(); },
  };
}

/* ------------------------------------------------------------------ */
/* Interaction wiring (navigation, run-band toggle, density jump)      */
/* ------------------------------------------------------------------ */

/** Toggle one run band: adds/removes `.run-active` on the matching rows.
    Returns the new expanded state (or null when the band is unusable). */
export function toggleRunBand(band) {
  if (!band || !band.getAttribute) return null;
  const index = String((band.dataset && band.dataset.runIndex) || band.getAttribute("data-run-index") || "");
  const expanded = band.getAttribute("aria-expanded") === "true";
  const next = !expanded;
  band.setAttribute("aria-expanded", next ? "true" : "false");
  const toggle = band.querySelector ? band.querySelector(".timeline-run-toggle") : null;
  if (toggle) toggle.textContent = next ? "收起" : "展开";
  let group = band.parentNode;
  while (group && !(group.classList && group.classList.contains("timeline-group"))) {
    group = group.parentNode;
  }
  if (!group || !group.querySelectorAll) return next;
  group.querySelectorAll(".timeline-item-row[data-run-indices]").forEach((row) => {
    const raw = (row.getAttribute && row.getAttribute("data-run-indices"))
      || (row.dataset && row.dataset.runIndices) || "";
    if (raw.split(",").filter(Boolean).includes(index) && row.classList) {
      row.classList.toggle("run-active", next);
    }
  });
  return next;
}

/** Wire the whole timeline: entry navigation (read-only `go`), run bands and
    the density bar jump.  No handler performs a write. */
export function wireTimeline(root, handlers = {}) {
  if (!root || !root.querySelectorAll) return;
  const go = handlers.go || (() => {});
  const scrollTo = handlers.scrollTo || (() => {});
  root.querySelectorAll("button.timeline-item[data-route]").forEach((button) => {
    button.addEventListener("click", () => {
      go((button.dataset && button.dataset.route) || button.getAttribute("data-route"));
    });
  });
  root.querySelectorAll(".timeline-run-band[data-run-index]").forEach((band) => {
    band.addEventListener("click", () => toggleRunBand(band));
  });
  root.querySelectorAll(".timeline-density-bar[data-group-key]").forEach((bar) => {
    bar.addEventListener("click", () => {
      scrollTo((bar.dataset && bar.dataset.groupKey) || bar.getAttribute("data-group-key"));
    });
  });
}
