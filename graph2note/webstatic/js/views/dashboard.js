/* graph2note — read-only local telemetry dashboard (U1 relocation; A2 adds the
   weekly-digest block here, inside the dashboard zone). */
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { esc, displayTime } from "../utils.js";
import { registerView } from "../router.js";
import { showViewError, clearViewError, showToast } from "../ui.js";
import { renderMarkdownInto } from "./document.js";

function dashboardValue(value, digits = 0) {
  if (value == null) return "不可用";
  return typeof value === "number" ? value.toFixed(digits) : String(value);
}

function dashboardCost(item, currency) {
  if (item.cost_status === "no_price_config") return "无价格配置";
  if (item.cost_status === "usage_unavailable" || item.cost_status === "tokens_incomplete") return "token 不可用";
  if (item.cost_status === "cached") return "缓存命中 · 无新增成本";
  if (item.cost == null) return "不可用";
  return `${Number(item.cost).toFixed(6)} ${esc(currency || "USD")}`;
}

function dashboardRows(items, labelKey, valueKey = "count") {
  if (!items || !items.length) return `<span class="dim">暂无数据</span>`;
  return items.map((item) => `<div class="dashboard-row">
    <span>${esc(item[labelKey])}</span><b>${esc(dashboardValue(item[valueKey]))}</b>
  </div>`).join("");
}

function renderDashboardBuckets(items, currency) {
  if (!items || !items.length) return `<span class="dim">暂无 token 遥测</span>`;
  return items.map((item) => `<div class="dashboard-bucket">
    <div><b>${esc(item.period)}</b><span class="dim">${dashboardValue(item.total_tokens)} tokens</span></div>
    <div class="dim">输入 ${dashboardValue(item.prompt_tokens)} · 输出 ${dashboardValue(item.completion_tokens)} · 推理 ${dashboardValue(item.reasoning_tokens)}</div>
    <div class="dashboard-cost">${dashboardCost(item, currency)}</div>
  </div>`).join("");
}

function renderDashboardModels(items, currency) {
  if (!items || !items.length) return `<span class="dim">暂无模型遥测</span>`;
  return `<div class="dashboard-model-list">${items.map((item) => `<div class="dashboard-model">
    <div class="dashboard-model-head"><b>${esc(item.model)}</b><span class="dim">${esc(item.provider || "供应商未知")}</span></div>
    <div class="dashboard-model-meta">${dashboardValue(item.total_tokens)} tokens · ${item.events} 次 · 重试 ${item.retries} 次 · 缓存 ${item.cached_hits} 次</div>
    <div class="dashboard-cost">成本：${dashboardCost(item, currency)}</div>
  </div>`).join("")}</div>`;
}

async function renderDashboard() {
  clearViewError(el.dashboardZone);
  el.dashboardZone.classList.remove("hidden");
  void renderDigestPanel();
  el.dashboardEmpty.classList.add("hidden");
  el.dashboardContent.classList.remove("hidden");
  try {
    const stats = await api("/api/stats");
    if (stats.empty_library) {
      el.dashboardEmpty.classList.remove("hidden");
      el.dashboardContent.classList.add("hidden");
      return;
    }
    const periods = stats.periods || {};
    el.dashboardPeriods.innerHTML = [
      ["今日解析", periods.today], ["本周解析", periods.week], ["累计解析", periods.total],
    ].map(([label, item]) => `<div class="dashboard-card"><span class="dim">${label}</span><strong>${dashboardValue(item && item.pages)}</strong><small>${dashboardValue(item && item.new_documents)} 个新文档</small></div>`).join("");
    const quality = stats.quality || {};
    const qualityText = quality.status === "complete" ? "遥测完整" : quality.status === "partial" ? `有 ${quality.missing_telemetry_events} 条旧记录缺少遥测` : "遥测不可用";
    el.dashboardQualityLabel.textContent = qualityText;
    el.dashboardQuality.innerHTML = `<div class="dashboard-quality-row"><span>平均耗时</span><b>${dashboardValue(quality.average_latency_seconds, 2)} 秒</b><span>重试率</span><b>${quality.retry_rate == null ? "不可用" : `${(quality.retry_rate * 100).toFixed(1)}%`}</b><span>可用遥测</span><b>${quality.telemetry_events}/${quality.total_events}</b></div>`;
    el.dashboardTrend.innerHTML = dashboardRows(stats.new_documents_trend, "date");
    el.dashboardCategories.innerHTML = dashboardRows(stats.classification_distribution, "topic");
    el.dashboardTags.innerHTML = dashboardRows(stats.top_tags, "tag");
    el.dashboardModels.innerHTML = renderDashboardModels(stats.model_usage, stats.currency);
    el.dashboardDay.innerHTML = renderDashboardBuckets(stats.token_usage_by_day, stats.currency);
    el.dashboardMonth.innerHTML = renderDashboardBuckets(stats.token_usage_by_month, stats.currency);
  } catch (e) {
    el.dashboardEmpty.classList.add("hidden");
    el.dashboardContent.classList.add("hidden");
    showViewError(el.dashboardZone, "加载数据看板失败：" + e.message, renderDashboard);
  }
}

registerView("dashboard", renderDashboard);

/* ---------- Weekly digest (issue A2; W2 sectioned view + export) ----------

   The generator writes a fixed four-section Markdown plus a machine-readable
   `sections: [{key, title, source_document_ids}]` contract into meta.json.
   This view consumes that contract:

   * meta.sections present: sectioned view with an anchor nav, per-section
     source-document links into the library and a compact stats strip;
   * legacy meta without sections: the previous whole-Markdown rendering;
   * every loaded digest can be exported as a `.md` file (frontend Blob).

   Nothing here generates content or calls the model.  The pure helpers and the
   digest entry points are exported for the offline DOM contract test
   (``tests/digest_view_dom.mjs``); the view module stays the single owner.
*/

const DIGEST_VIEW_INBOX_CAVEAT =
  "Inbox 统计沿用库投影口径：只缺标签的文档也算待整理；材料分区只把完全无主题/标签"
  + "或显式标记的文档算作待整理。两个口径不同，不能相加。";

/* Digest panel state.  The DOM owns what is displayed; this only keeps the
   payload needed for export and the resolved library index. */
const digestView = {
  meta: null,
  markdown: "",
  known: null,        // Map(document_id -> title); null until the list answers
  knownTried: false,
  historyFailed: false,
  controlsReady: false,
  actions: null,
  exportButton: null,
};

export function digestRangeLabel(meta) {
  const range = (meta && meta.range) || {};
  return range.label || `${range.from || "?"} ~ ${range.to || "?"}`;
}

export function digestSectionAnchor(key) {
  return "digest-section-" + String(key || "").replace(/[^A-Za-z0-9_-]/g, "-");
}

export function digestLlmModeLabel(mode) {
  const labels = { json: "模型分节", "text-fallback": "散文回退", "section-cache": "分节缓存复用" };
  return labels[mode] || String(mode || "未知");
}

/* Split the digest Markdown at its `## ` headings and map every block to a
   declared section.  Blocks that are not one of the declared sections (the
   lead paragraph, the trailing `## 来源` block, ...) come back as extras so the
   sectioned view never drops content.  Declared sections missing from the
   Markdown still get an explicit (empty) slot.  Pure. */
export function splitDigestMarkdown(markdown, sections) {
  const parts = [];
  let lead = "";
  let current = null;
  for (const line of String(markdown || "").split("\n")) {
    const heading = /^##\s+(.*)$/.exec(line);
    if (heading) {
      current = { title: heading[1].trim(), lines: [] };
      parts.push(current);
    } else if (current) {
      current.lines.push(line);
    } else {
      lead += line + "\n";
    }
  }
  const byTitle = new Map();
  for (const section of sections || []) byTitle.set(String(section.title || "").trim(), section);
  const out = [];
  const extras = [];
  for (const part of parts) {
    const declared = byTitle.get(part.title);
    const body = part.lines.join("\n").trim();
    if (declared && !out.some((item) => item.key === declared.key)) {
      out.push({
        key: declared.key,
        title: declared.title || part.title,
        body,
        source_document_ids: declared.source_document_ids || [],
      });
    } else {
      extras.push({ title: part.title, body });
    }
  }
  for (const section of sections || []) {
    if (!out.some((item) => item.key === section.key)) {
      out.push({
        key: section.key,
        title: section.title || section.key,
        body: "",
        source_document_ids: section.source_document_ids || [],
      });
    }
  }
  return { lead: lead.trim(), sections: out, extras };
}

export function digestMetaSummary(meta) {
  if (!meta) return "";
  const bits = [digestRangeLabel(meta), `${meta.document_count || 0} 篇`];
  if (Array.isArray(meta.sections) && meta.sections.length) bits.push(`${meta.sections.length} 节`);
  if (meta.llm_mode) bits.push(`生成方式：${digestLlmModeLabel(meta.llm_mode)}`);
  const fingerprint = String(meta.fingerprint || "").slice(0, 12);
  if (fingerprint) bits.push(`指纹 ${fingerprint}`);
  return bits.join(" · ");
}

export function formatTokenCount(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "";
  return String(Math.round(num)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/* One readable history line: scope, time and generation cost stay separated so
   the numbers keep their meaning (R8: meta.document_count is the selected
   material, not the whole range). */
export function digestHistorySummary(meta) {
  const usage = (meta && meta.usage) || {};
  const bits = [`${(meta && meta.document_count) || 0} 篇`];
  if (meta && meta.model) bits.push(String(meta.model));
  bits.push(usage.total_tokens != null
    ? `${formatTokenCount(usage.total_tokens)} tokens`
    : "token 不可用");
  if (meta && meta.llm_calls != null) {
    bits.push(meta.llm_calls ? `模型调用 ${meta.llm_calls} 次` : "缓存复用");
  }
  return bits.join(" · ");
}

/* W2 §R2: the Inbox projection and the material partition are not the same
   number.  Whenever both can be displayed they carry an explicit caveat. */
export function digestStatsSummary(meta) {
  const stats = (meta && meta.stats) || {};
  const chips = [];
  const push = (label, value, title) => {
    if (value == null || value === "") return;
    chips.push({ label, value: String(value), title: title || "" });
  };
  push("范围内", stats.document_count != null ? `${stats.document_count} 篇` : "",
    "范围内命中的全部文档（含未被材料预算选入的）");
  push("选入材料", meta && meta.document_count != null ? `${meta.document_count} 篇` : "",
    "实际进入本次小结材料的文档（受材料预算裁剪）");
  if (stats.parsed_count != null) {
    push("解析成功", `${stats.parsed_count}/${stats.document_count}`, "正文非空的材料文档");
  }
  push("新增", stats.new_document_count != null ? `${stats.new_document_count} 篇` : "",
    "范围内新建的文档");
  if (stats.topic_count != null || stats.tag_count != null) {
    push("主题/标签", `${stats.topic_count || 0} / ${stats.tag_count || 0}`, "材料覆盖的主题数与标签数");
  }
  push("Inbox 本期", stats.inbox_in_range != null ? `${stats.inbox_in_range} 篇` : "",
    DIGEST_VIEW_INBOX_CAVEAT);
  push("连续体", stats.continuity_significant != null ? `可合并 ${stats.continuity_significant} 对` : "",
    "仅统计显著对；库规模超阈值时不计待确认对");
  return chips;
}

export function digestExportFilename(meta) {
  const range = (meta && meta.range) || {};
  const part = (value) => String(value || "")
    .replace(/[^0-9A-Za-z._-]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
  const created = part(String((meta && meta.created_at) || "").slice(0, 10));
  return `weekly-digest_${part(range.from)}_${part(range.to)}_${created}.md`;
}

function updateDigestCustomFields() {
  const custom = el.digestRange && el.digestRange.value === "custom";
  [el.digestFrom, el.digestTo, el.digestFromSep].forEach((node) => {
    if (node) node.classList.toggle("hidden", !custom);
  });
}

function setDigestEmpty(message) {
  if (!el.digestEmpty) return;
  el.digestEmpty.textContent = message || "该范围内没有材料。";
  el.digestEmpty.classList.remove("hidden");
  el.digestViewerContent.classList.add("hidden");
}

function setDigestStatus(message, kind = "") {
  if (!el.digestStatus) return;
  el.digestStatus.textContent = message || "";
  el.digestStatus.className = "dim digest-status" + (kind ? ` digest-status-${kind}` : "");
}

function setDigestBusy(busy) {
  if (el.digestGenerate) {
    el.digestGenerate.disabled = !!busy;
    el.digestGenerate.textContent = busy ? "生成中…" : "生成小结";
  }
  if (el.digestPanel) el.digestPanel.setAttribute("aria-busy", busy ? "true" : "false");
}

/* Export button + the state-action row are created from JS: the digest markup
   in index.html stays untouched (W2 territory is dashboard.js only). */
function ensureDigestControls() {
  if (digestView.controlsReady || !el.digestPanel) return;
  digestView.controlsReady = true;
  const controls = el.digestPanel.querySelector(".digest-controls");
  if (controls && !controls.querySelector("#digest-export")) {
    const button = document.createElement("button");
    button.id = "digest-export";
    button.type = "button";
    button.className = "btn small";
    button.textContent = "导出 Markdown";
    button.disabled = true;
    button.addEventListener("click", () => { exportCurrentDigest(); });
    controls.appendChild(button);
    digestView.exportButton = button;
  }
  if (el.digestStatus && el.digestStatus.parentNode && !digestView.actions) {
    const row = document.createElement("div");
    row.id = "digest-actions";
    row.className = "digest-actions hidden";
    el.digestStatus.parentNode.insertBefore(row, el.digestStatus.nextSibling || null);
    digestView.actions = row;
  }
}

function focusDigestRange() {
  if (el.digestRange && el.digestRange.focus) el.digestRange.focus();
}

function setDigestActions(actions) {
  const row = digestView.actions;
  if (!row) return;
  row.innerHTML = "";
  row.classList.toggle("hidden", !(actions && actions.length));
  (actions || []).forEach((spec) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn small" + (spec.primary ? " primary" : "");
    button.textContent = spec.label;
    button.addEventListener("click", spec.run);
    row.appendChild(button);
  });
}

function updateDigestExportButton() {
  if (digestView.exportButton) digestView.exportButton.disabled = !digestView.markdown;
}

/* /api/documents gives the library index used to resolve source ids to titles
   and to grey out ids that no longer exist.  When the list is unavailable the
   links stay clickable and no id is declared dead. */
async function loadKnownDocuments() {
  if (digestView.knownTried) return digestView.known;
  digestView.knownTried = true;
  try {
    const list = await api("/api/documents");
    const index = new Map();
    (Array.isArray(list) ? list : []).forEach((doc) => {
      if (doc && doc.document_id) index.set(String(doc.document_id), doc.title || String(doc.document_id));
    });
    digestView.known = index;
  } catch (e) {
    digestView.known = null;
  }
  return digestView.known;
}

function buildSourceChips(ids, known) {
  const out = [];
  (ids || []).forEach((rawId) => {
    const id = String(rawId);
    const missing = !!known && !known.has(id);
    const title = known ? known.get(id) : undefined;
    let node;
    if (missing) {
      node = document.createElement("button");
      node.type = "button";
      node.className = "digest-source digest-source-missing";
      node.title = `库中已不存在该文档：${id}`;
      node.textContent = id;
      node.addEventListener("click", () => showToast(`来源文档已不在库中：${id}`, "err"));
    } else {
      node = document.createElement("a");
      node.className = "digest-source";
      node.href = `#doc/${encodeURIComponent(id)}`;
      node.setAttribute("data-document-id", id);
      node.title = title ? `${title}（${id}）` : id;
      node.textContent = title || id;
    }
    out.push(node);
  });
  return out;
}

function buildDigestSection(section, known) {
  const box = document.createElement("section");
  box.className = "digest-section";
  box.id = digestSectionAnchor(section.key);
  box.setAttribute("data-section", section.key);
  box.setAttribute("tabindex", "-1");
  const title = document.createElement("h3");
  title.className = "digest-section-title";
  title.textContent = section.title;
  box.appendChild(title);
  const body = document.createElement("div");
  body.className = "digest-section-body preview";
  renderMarkdownInto(body, section.body || "_（本节没有可归纳的内容）_");
  box.appendChild(body);
  const sources = document.createElement("div");
  sources.className = "digest-section-sources";
  const label = document.createElement("span");
  label.className = "digest-sources-label dim";
  label.textContent = "来源文档";
  sources.appendChild(label);
  const chips = buildSourceChips(section.source_document_ids, known);
  if (chips.length) {
    chips.forEach((chip) => sources.appendChild(chip));
  } else {
    const none = document.createElement("span");
    none.className = "dim";
    none.textContent = "本节没有可跳转的来源。";
    sources.appendChild(none);
  }
  box.appendChild(sources);
  return box;
}

function buildDigestNav(sections, sectionNodes) {
  const nav = document.createElement("nav");
  nav.className = "digest-section-nav";
  nav.setAttribute("aria-label", "小结分节导航");
  sections.forEach((section) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "digest-nav-link";
    button.setAttribute("data-section", section.key);
    const label = document.createElement("span");
    label.textContent = section.title;
    const count = document.createElement("span");
    count.className = "digest-nav-count dim";
    count.textContent = String((section.source_document_ids || []).length);
    button.appendChild(label);
    button.appendChild(count);
    button.addEventListener("click", () => {
      const target = sectionNodes.get(section.key);
      if (!target) return;
      if (target.scrollIntoView) target.scrollIntoView({ block: "start" });
      if (target.focus) target.focus();
    });
    nav.appendChild(button);
  });
  return nav;
}

function buildDigestStats(meta) {
  const chips = digestStatsSummary(meta);
  if (!chips.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "digest-stats";
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", "本期统计");
  chips.forEach((chip) => {
    const item = document.createElement("span");
    item.className = "digest-stat";
    if (chip.title) item.title = chip.title;
    const label = document.createElement("span");
    label.className = "dim";
    label.textContent = chip.label;
    const value = document.createElement("b");
    value.textContent = chip.value;
    item.appendChild(label);
    item.appendChild(value);
    wrap.appendChild(item);
  });
  const block = document.createElement("div");
  block.className = "digest-stats-block";
  block.appendChild(wrap);
  if (chips.some((chip) => chip.label.startsWith("Inbox") || chip.label.startsWith("选入材料"))) {
    const note = document.createElement("p");
    note.className = "digest-stats-note dim";
    note.textContent = "※ " + DIGEST_VIEW_INBOX_CAVEAT;
    block.appendChild(note);
  }
  return block;
}

function renderDigestSectioned(viewer, meta, markdown) {
  const parsed = splitDigestMarkdown(markdown, meta.sections || []);
  const known = digestView.known;
  viewer.innerHTML = "";
  const stats = buildDigestStats(meta);
  if (stats) viewer.appendChild(stats);
  if (parsed.lead) {
    const lead = document.createElement("div");
    lead.className = "digest-lead preview";
    renderMarkdownInto(lead, parsed.lead);
    viewer.appendChild(lead);
  }
  const sectionNodes = new Map();
  const list = document.createElement("div");
  list.className = "digest-section-list";
  parsed.sections.forEach((section) => {
    const box = buildDigestSection(section, known);
    sectionNodes.set(section.key, box);
    list.appendChild(box);
  });
  viewer.appendChild(buildDigestNav(parsed.sections, sectionNodes));
  viewer.appendChild(list);
  if (parsed.extras.length) {
    const extra = document.createElement("div");
    extra.className = "digest-extra";
    parsed.extras.forEach((part) => {
      const box = document.createElement("section");
      box.className = "digest-section digest-extra-block";
      const title = document.createElement("h3");
      title.className = "digest-section-title";
      title.textContent = part.title;
      const body = document.createElement("div");
      body.className = "digest-section-body preview";
      renderMarkdownInto(body, part.body || "");
      box.appendChild(title);
      box.appendChild(body);
      extra.appendChild(box);
    });
    viewer.appendChild(extra);
  }
}

export function renderDigestHistory(metas) {
  if (!el.digestHistory) return;
  const list = Array.isArray(metas) ? metas : [];
  if (!list.length) {
    el.digestHistory.innerHTML = `<li class="dim">还没有生成过小结。</li>`;
    return;
  }
  el.digestHistory.innerHTML = list.map((meta) => {
    const selected = state.digestId === meta.digest_id;
    return `<li><button type="button" class="digest-item ${selected ? "selected" : ""}"`
      + ` data-digest-id="${esc(meta.digest_id)}"${selected ? ' aria-current="true"' : ""}>
      <span class="digest-item-range">${esc(digestRangeLabel(meta))}</span>
      <span class="digest-item-time dim">生成时间：${esc(displayTime(meta.created_at))}</span>
      <span class="digest-item-summary dim">${esc(digestHistorySummary(meta))}</span>
    </button></li>`;
  }).join("");
  el.digestHistory.querySelectorAll("button.digest-item[data-digest-id]").forEach((button) => {
    button.addEventListener("click", () => openDigest(button.dataset.digestId));
  });
}

async function loadDigestHistory() {
  if (!el.digestHistory) return [];
  try {
    const payload = await api("/api/digests");
    const metas = Array.isArray(payload && payload.digests) ? payload.digests : [];
    digestView.historyFailed = false;
    renderDigestHistory(metas);
    return metas;
  } catch (e) {
    digestView.historyFailed = true;
    el.digestHistory.innerHTML = `<li class="dim digest-history-error">历史小结加载失败：${esc(e.message)}
      <button type="button" class="btn small" data-digest-history-retry="1">重试</button></li>`;
    const retry = el.digestHistory.querySelector("button[data-digest-history-retry]");
    if (retry) retry.addEventListener("click", () => { void loadDigestHistory(); });
    return [];
  }
}

/* Sectioned path (meta.sections) and legacy whole-Markdown fallback. */
export async function showDigest(meta, markdown) {
  digestView.meta = meta || null;
  digestView.markdown = String(markdown || "");
  const sections = meta && Array.isArray(meta.sections) ? meta.sections.filter((s) => s && s.key) : [];
  if (el.digestViewerMeta) el.digestViewerMeta.textContent = meta ? digestMetaSummary(meta) : "";
  updateDigestExportButton();
  if (!digestView.markdown) {
    el.digestViewerContent.classList.add("hidden");
    el.digestViewerContent.innerHTML = "";
    el.digestEmpty.classList.remove("hidden");
    return;
  }
  el.digestEmpty.classList.add("hidden");
  el.digestViewerContent.classList.remove("hidden");
  if (sections.length) {
    await loadKnownDocuments();
    renderDigestSectioned(el.digestViewerContent, meta, digestView.markdown);
  } else {
    renderMarkdownInto(el.digestViewerContent, digestView.markdown);
  }
}

/* Frontend Blob download: the digest Markdown is already in memory, so this
   needs no server round-trip and no new API endpoint.  Returns the filename. */
export function exportCurrentDigest() {
  if (!digestView.markdown) {
    showToast("还没有可导出的周报。", "err");
    return "";
  }
  const filename = digestExportFilename(digestView.meta);
  try {
    const blob = new Blob([digestView.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    showToast("已导出 " + filename);
  } catch (e) {
    showToast("导出失败：" + e.message, "err");
  }
  return filename;
}

export async function openDigest(digestId) {
  if (!digestId) return;
  state.digestId = digestId;
  setDigestStatus("读取小结…");
  setDigestActions([]);
  try {
    const payload = await api(`/api/digests/${encodeURIComponent(digestId)}`);
    await showDigest(payload.meta || null, payload.markdown || "");
    setDigestStatus("");
    await loadDigestHistory();
  } catch (e) {
    setDigestStatus("读取失败：" + e.message, "error");
    setDigestActions([
      { label: "重新读取", primary: true, run: () => openDigest(digestId) },
      { label: "修改范围", run: focusDigestRange },
    ]);
  }
}

async function generateDigest() {
  const payload = {
    range: el.digestRange.value,
    force: !!(el.digestForce && el.digestForce.checked),
  };
  if (el.digestRange.value === "custom") {
    payload.from = el.digestFrom.value;
    payload.to = el.digestTo.value;
  }
  setDigestBusy(true);
  setDigestStatus("生成中…（同一指纹会直接复用缓存）");
  setDigestActions([]);
  try {
    const r = await api("/api/digests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (r.status === "empty") {
      state.digestId = null;
      await showDigest(
        { range: r.range, document_count: 0, fingerprint: r.fingerprint, document_ids: [], sections: [] },
        "",
      );
      setDigestEmpty(r.message || "该范围内没有材料。");
      setDigestStatus(r.message || "该范围内没有材料。");
      setDigestActions([
        { label: "修改范围", run: focusDigestRange },
        { label: "再试一次", primary: true, run: generateDigest },
      ]);
    } else {
      state.digestId = r.digest ? r.digest.digest_id : null;
      await showDigest(r.digest || null, r.markdown || "");
      setDigestStatus(r.cached ? "命中缓存，未重新调用模型。" : "已生成并保存。");
      setDigestActions([]);
    }
    await loadDigestHistory();
  } catch (e) {
    setDigestStatus("生成失败：" + e.message, "error");
    setDigestActions([
      { label: "重试生成", primary: true, run: generateDigest },
      { label: "修改范围", run: focusDigestRange },
    ]);
    showToast("生成失败：" + e.message, "err");
  } finally {
    setDigestBusy(false);
  }
}

export async function renderDigestPanel() {
  if (!el.digestPanel) return;
  ensureDigestControls();
  updateDigestCustomFields();
  // refresh the library index once per panel render so dead ids recover
  digestView.known = null;
  digestView.knownTried = false;
  const metas = await loadDigestHistory();
  if (digestView.historyFailed) return;   // keep the inline retry, never claim "no digests"
  if (metas.length && !state.digestId) {
    await openDigest(metas[0].digest_id);
  } else if (!metas.length) {
    await showDigest(null, "");
    setDigestEmpty("还没有生成过小结。选择范围后点「生成小结」。");
    setDigestActions([
      { label: "生成小结", primary: true, run: generateDigest },
      { label: "选择范围", run: focusDigestRange },
    ]);
  }
}

if (el.digestRange) {
  el.digestRange.addEventListener("change", updateDigestCustomFields);
  el.digestGenerate.addEventListener("click", generateDigest);
}
