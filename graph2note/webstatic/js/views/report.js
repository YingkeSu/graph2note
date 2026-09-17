/* graph2note — 科研周报 (research weekly report, research-weekly-template 01).

   The backend `research_report` module owns a *versioned* research template
   (概览 / 进展 / 问题与求助 + optional 专题) and a legacy four-section summary
   template.  This view is the reading surface:

   * range + reporter + report date, template selector;
   * optional 专题 list with per-module enable and ↑/↓ order — the exact config
     sent to the API, so the cache key matches what was generated;
   * history with template/range/time/cost, reopen after restart;
   * sectioned reading view with per-section source links into the library,
     a deterministic stats/budget strip, per-section generator badge and a
     model-failure state with retry actions;
   * frontend Blob export of the exact Markdown snapshot.

   It never generates content itself and never calls the model.  Pure helpers are
   exported for the offline DOM contract test (`tests/report_view_dom.mjs`).
*/
"use strict";

import { api } from "../api.js";
import { esc, displayTime } from "../utils.js";
import { registerView } from "../router.js";
import { showToast } from "../ui.js";
import { renderMarkdownInto } from "./document.js";

const RESEARCH_TEMPLATE = "research_weekly";
const LEGACY_TEMPLATE = "weekly_summary";
const MODULE_STORAGE_KEY = "graph2note.report.modules";

const reportView = {
  templates: [],
  catalog: [],
  modules: null,
  meta: null,
  markdown: "",
  reportId: null,
  template: RESEARCH_TEMPLATE,
  known: null,
  knownTried: false,
  busy: false,
};

const el = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ pure */

export function reportTemplateLabel(id) {
  // A legacy digest meta predates the template_id field: treat it as the legacy
  // four-section summary rather than "unknown".
  if (id == null || id === "" || id === LEGACY_TEMPLATE) return "旧版四节小结";
  if (id === RESEARCH_TEMPLATE) return "科研周报";
  return String(id || "未知模板");
}

export function reportSectionAnchor(key) {
  return "report-section-" + String(key || "").replace(/[^A-Za-z0-9_-]/g, "-");
}

export function reportLlmModeLabel(mode) {
  const labels = {
    json: "模型分节", "text-fallback": "散文回退", "section-cache": "缓存复用",
    deterministic: "确定性生成", empty: "无模型内容",
  };
  return labels[mode] || String(mode || "未知");
}

/* Split a report Markdown at its `## ` headings, mapping blocks to declared
   sections.  Content not owned by a declared section is preserved as extras so
   the viewer never drops anything.  Pure. */
export function splitReportMarkdown(markdown, sections) {
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
        generated_by: declared.generated_by || "",
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
        generated_by: section.generated_by || "",
      });
    }
  }
  return { lead: lead.trim(), sections: out, extras };
}

/* Merge the catalog with a saved config: saved order + enabled flags win, any
   catalog module not mentioned is appended disabled.  Pure. */
export function normalizeModuleConfig(catalog, saved) {
  const remaining = new Map();
  (catalog || []).forEach((m) => { if (m && m.key) remaining.set(String(m.key), m); });
  const out = [];
  const push = (module) => {
    if (!module || !module.key) return;
    const key = String(module.key);
    const known = remaining.get(key);
    remaining.delete(key);
    out.push({
      key,
      title: module.title || (known && known.title) || key,
      enabled: !!module.enabled,
    });
  };
  (Array.isArray(saved) ? saved : []).forEach(push);
  (catalog || []).forEach((m) => { if (m && m.key && remaining.has(String(m.key))) push(m); });
  return out;
}

export function reportEnabledModules(modules) {
  return (modules || []).filter((m) => m && m.enabled);
}

/* Deterministic stats strip: counts come from meta.stats (range scope) and
   meta.document_count (selected material), never from the model. */
export function reportStatsSummary(meta) {
  const stats = (meta && meta.stats) || {};
  const chips = [];
  const push = (label, value, title) => {
    if (value == null || value === "") return;
    chips.push({ label, value: String(value), title: title || "" });
  };
  push("范围内", stats.document_count != null ? `${stats.document_count} 篇` : "",
    "范围内命中的全部文档（含未被材料预算选入的）");
  push("选入材料", meta && meta.document_count != null ? `${meta.document_count} 篇` : "",
    "实际进入本次周报材料的文档（受材料预算裁剪）");
  if (stats.parsed_count != null) {
    push("解析成功", `${stats.parsed_count}/${stats.document_count}`,
      "正文非空的材料文档");
  }
  push("新增", stats.new_document_count != null ? `${stats.new_document_count} 篇` : "",
    "范围内新建的文档");
  if (stats.topic_count != null || stats.tag_count != null) {
    push("主题/标签", `${stats.topic_count || 0} / ${stats.tag_count || 0}`,
      "材料覆盖的主题数与标签数");
  }
  return chips;
}

export function reportBudgetSummary(meta) {
  const budget = (meta && meta.budget) || {};
  if (budget.total == null) return "";
  return `材料预算：范围内 ${budget.total} 篇 → 选入 ${budget.kept} 篇，省略 `
    + `${budget.omitted} 篇（有效时间优先，每主题保底 ${budget.topic_floor} 篇，上限 ${budget.max_docs} 篇）`;
}

export function reportMetaSummary(meta) {
  if (!meta) return "";
  const range = (meta.range || {});
  const bits = [reportTemplateLabel(meta.template_id)];
  if (meta.template_version) bits.push(`v${meta.template_version}`);
  bits.push(range.label || `${range.from || "?"} ~ ${range.to || "?"}`);
  if (meta.reporter) bits.push(`汇报人：${meta.reporter}`);
  if (meta.report_date) bits.push(`日期：${meta.report_date}`);
  bits.push(`${meta.document_count || 0} 篇材料`);
  if (meta.llm_mode) bits.push(`生成方式：${reportLlmModeLabel(meta.llm_mode)}`);
  const fingerprint = String(meta.fingerprint || "").slice(0, 12);
  if (fingerprint) bits.push(`指纹 ${fingerprint}`);
  return bits.join(" · ");
}

export function reportHistorySummary(meta) {
  const usage = (meta && meta.usage) || {};
  const bits = [`${(meta && meta.document_count) || 0} 篇`];
  if (meta && meta.model) bits.push(String(meta.model));
  bits.push(usage.total_tokens != null ? `${usage.total_tokens} tokens` : "token 不可用");
  if (meta && meta.llm_calls != null) {
    bits.push(meta.llm_calls ? `模型调用 ${meta.llm_calls} 次` : "缓存复用");
  }
  return bits.join(" · ");
}

export function reportExportFilename(meta) {
  const range = (meta && meta.range) || {};
  const part = (value) => String(value || "")
    .replace(/[^0-9A-Za-z._-]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
  const created = part(String((meta && meta.created_at) || "").slice(0, 10));
  const legacy = !meta || !meta.template_id || meta.template_id === LEGACY_TEMPLATE;
  const prefix = legacy ? "weekly-summary" : "research-weekly";
  return `${prefix}_${part(range.from)}_${part(range.to)}_${created}.md`;
}

/* --------------------------------------------------------------- rendering */

function setReportStatus(message, kind = "") {
  const node = el("report-status");
  if (!node) return;
  node.textContent = message || "";
  node.className = "dim report-status" + (kind ? ` report-status-${kind}` : "");
}

function setReportActions(actions) {
  const row = el("report-actions");
  if (!row) return;
  row.innerHTML = "";
  const list = actions || [];
  row.classList.toggle("hidden", !list.length);
  list.forEach((spec) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn small" + (spec.primary ? " primary" : "");
    button.textContent = spec.label;
    button.addEventListener("click", spec.run);
    row.appendChild(button);
  });
}

function setReportBusy(busy) {
  reportView.busy = !!busy;
  const button = el("report-generate");
  if (button) {
    button.disabled = !!busy;
    button.textContent = busy ? "生成中…" : "生成科研周报";
  }
  const zone = el("report-zone");
  if (zone) zone.setAttribute("aria-busy", busy ? "true" : "false");
}

function updateReportExportButton() {
  const button = el("report-export");
  if (button) button.disabled = !reportView.markdown;
}

function updateReportCustomFields() {
  const select = el("report-range");
  const custom = select && select.value === "custom";
  ["report-from", "report-to", "report-from-sep"].forEach((id) => {
    const node = el(id);
    if (node) node.classList.toggle("hidden", !custom);
  });
}

function updateTemplateVisibility() {
  const legacy = reportView.template === LEGACY_TEMPLATE;
  const modules = el("report-modules");
  if (modules) modules.classList.toggle("hidden", legacy);
  const reporter = el("report-reporter");
  const date = el("report-date");
  [reporter, date].forEach((node) => { if (node) node.disabled = legacy; });
}

function saveModuleConfig() {
  if (reportView.template === LEGACY_TEMPLATE) return;
  try {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(MODULE_STORAGE_KEY, JSON.stringify(reportView.modules || []));
    }
  } catch (e) { /* storage disabled: config stays in memory */ }
}

function renderModuleList() {
  const list = el("report-module-list");
  if (!list) return;
  list.innerHTML = "";
  const modules = reportView.modules || [];
  modules.forEach((module, index) => {
    const item = document.createElement("li");
    item.className = "report-module";
    item.dataset.moduleKey = module.key;

    const label = document.createElement("label");
    label.className = "report-module-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "report-module-enabled";
    checkbox.dataset.moduleKey = module.key;
    checkbox.checked = !!module.enabled;
    checkbox.addEventListener("change", () => {
      module.enabled = !!checkbox.checked;
      saveModuleConfig();
      renderModuleList();
    });
    const title = document.createElement("span");
    title.textContent = module.title;
    label.appendChild(checkbox);
    label.appendChild(title);

    const order = document.createElement("span");
    order.className = "report-module-order";
    const up = document.createElement("button");
    up.type = "button";
    up.className = "btn small report-module-up";
    up.textContent = "↑";
    up.disabled = index === 0;
    up.title = "上移";
    up.addEventListener("click", () => {
      if (index === 0) return;
      const next = reportView.modules.slice();
      [next[index - 1], next[index]] = [next[index], next[index - 1]];
      reportView.modules = next;
      saveModuleConfig();
      renderModuleList();
    });
    const down = document.createElement("button");
    down.type = "button";
    down.className = "btn small report-module-down";
    down.textContent = "↓";
    down.disabled = index === modules.length - 1;
    down.title = "下移";
    down.addEventListener("click", () => {
      if (index >= reportView.modules.length - 1) return;
      const next = reportView.modules.slice();
      [next[index + 1], next[index]] = [next[index], next[index + 1]];
      reportView.modules = next;
      saveModuleConfig();
      renderModuleList();
    });
    order.appendChild(up);
    order.appendChild(down);

    item.appendChild(label);
    item.appendChild(order);
    list.appendChild(item);
  });
}

async function loadReportTemplates() {
  const payload = await api("/api/report-templates");
  const list = Array.isArray(payload && payload.templates) ? payload.templates : [];
  reportView.templates = list;
  reportView.catalog = (Array.isArray(payload && payload.modules) ? payload.modules : [])
    .map((m) => ({ key: String(m.key), title: m.title || String(m.key) }));
  let saved = null;
  try {
    if (typeof localStorage !== "undefined") {
      saved = JSON.parse(localStorage.getItem(MODULE_STORAGE_KEY) || "null");
    }
  } catch (e) { saved = null; }
  reportView.modules = normalizeModuleConfig(reportView.catalog, saved);
  const select = el("report-template");
  if (select) {
    select.innerHTML = "";
    list.forEach((template) => {
      const option = document.createElement("option");
      option.value = template.id;
      option.textContent = `${template.label}${template.version ? ` (v${template.version})` : ""}`;
      select.appendChild(option);
    });
    if (!list.some((t) => t.id === reportView.template)) {
      reportView.template = list.length ? list[0].id : RESEARCH_TEMPLATE;
    }
    select.value = reportView.template;
  }
  renderModuleList();
  updateTemplateVisibility();
}

async function loadKnownDocuments() {
  if (reportView.knownTried) return reportView.known;
  reportView.knownTried = true;
  try {
    const list = await api("/api/documents");
    const index = new Map();
    (Array.isArray(list) ? list : []).forEach((doc) => {
      if (doc && doc.document_id) {
        index.set(String(doc.document_id), doc.title || String(doc.document_id));
      }
    });
    reportView.known = index;
  } catch (e) {
    reportView.known = null;
  }
  return reportView.known;
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
      node.className = "report-source report-source-missing";
      node.title = `库中已不存在该文档：${id}`;
      node.textContent = id;
      node.addEventListener("click", () => showToast(`来源文档已不在库中：${id}`, "err"));
    } else {
      node = document.createElement("a");
      node.className = "report-source";
      node.href = `#doc/${encodeURIComponent(id)}`;
      node.setAttribute("data-document-id", id);
      node.title = title ? `${title}（${id}）` : id;
      node.textContent = title || id;
    }
    out.push(node);
  });
  return out;
}

function buildReportSection(section, known) {
  const box = document.createElement("section");
  box.className = "report-section";
  box.id = reportSectionAnchor(section.key);
  box.setAttribute("data-section", section.key);
  box.setAttribute("tabindex", "-1");

  const title = document.createElement("h3");
  title.className = "report-section-title";
  title.textContent = section.title;
  box.appendChild(title);

  if (section.generated_by) {
    const badge = document.createElement("span");
    badge.className = "report-section-badge dim";
    badge.textContent = reportLlmModeLabel(section.generated_by);
    box.appendChild(badge);
  }

  const body = document.createElement("div");
  body.className = "report-section-body preview";
  renderMarkdownInto(body, section.body || "_（本节暂无内容）_");
  box.appendChild(body);

  const sources = document.createElement("div");
  sources.className = "report-section-sources";
  const label = document.createElement("span");
  label.className = "report-sources-label dim";
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

function buildReportStats(meta) {
  const chips = reportStatsSummary(meta);
  const budget = reportBudgetSummary(meta);
  if (!chips.length && !budget) return null;
  const block = document.createElement("div");
  block.className = "report-stats-block";
  if (chips.length) {
    const wrap = document.createElement("div");
    wrap.className = "report-stats";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "本期统计");
    chips.forEach((chip) => {
      const item = document.createElement("span");
      item.className = "report-stat";
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
    block.appendChild(wrap);
  }
  if (budget) {
    const note = document.createElement("p");
    note.className = "report-budget-note dim";
    note.textContent = budget;
    block.appendChild(note);
  }
  return block;
}

function renderReportSectioned(viewer, meta, markdown) {
  const sections = Array.isArray(meta && meta.sections) ? meta.sections : [];
  const parsed = splitReportMarkdown(markdown, sections);
  const known = reportView.known;
  viewer.innerHTML = "";
  const stats = buildReportStats(meta);
  if (stats) viewer.appendChild(stats);
  if (parsed.lead) {
    const lead = document.createElement("div");
    lead.className = "report-lead preview";
    renderMarkdownInto(lead, parsed.lead);
    viewer.appendChild(lead);
  }
  const sectionNodes = new Map();
  const list = document.createElement("div");
  list.className = "report-section-list";
  parsed.sections.forEach((section) => {
    const box = buildReportSection(section, known);
    sectionNodes.set(section.key, box);
    list.appendChild(box);
  });
  if (parsed.sections.length) {
    const nav = document.createElement("nav");
    nav.className = "report-section-nav";
    nav.setAttribute("aria-label", "周报分节导航");
    parsed.sections.forEach((section) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "report-nav-link";
      button.setAttribute("data-section", section.key);
      button.textContent = section.title;
      button.addEventListener("click", () => {
        const target = sectionNodes.get(section.key);
        if (!target) return;
        if (target.scrollIntoView) target.scrollIntoView({ block: "start" });
        if (target.focus) target.focus();
      });
      nav.appendChild(button);
    });
    viewer.appendChild(nav);
  }
  viewer.appendChild(list);
  if (parsed.extras.length) {
    const extra = document.createElement("div");
    extra.className = "report-extra";
    parsed.extras.forEach((part) => {
      const box = document.createElement("section");
      box.className = "report-section report-extra-block";
      const title = document.createElement("h3");
      title.className = "report-section-title";
      title.textContent = part.title;
      const body = document.createElement("div");
      body.className = "report-section-body preview";
      renderMarkdownInto(body, part.body || "");
      box.appendChild(title);
      box.appendChild(body);
      extra.appendChild(box);
    });
    viewer.appendChild(extra);
  }
}

function showReportEmpty(message) {
  reportView.markdown = "";
  const empty = el("report-empty");
  const content = el("report-viewer-content");
  const metaNode = el("report-viewer-meta");
  const statsNode = el("report-viewer-stats");
  if (metaNode) metaNode.textContent = "";
  if (statsNode) statsNode.innerHTML = "";
  if (content) {
    content.classList.add("hidden");
    content.innerHTML = "";
  }
  if (empty) {
    empty.textContent = message || "还没有生成过科研周报。";
    empty.classList.remove("hidden");
  }
  updateReportExportButton();
}

export async function showReport(meta, markdown) {
  reportView.meta = meta || null;
  reportView.markdown = String(markdown || "");
  updateReportExportButton();
  const metaNode = el("report-viewer-meta");
  const statsNode = el("report-viewer-stats");
  const content = el("report-viewer-content");
  const empty = el("report-empty");
  if (metaNode) metaNode.textContent = meta ? reportMetaSummary(meta) : "";
  if (statsNode) statsNode.innerHTML = "";
  if (!reportView.markdown) {
    showReportEmpty("该范围内没有材料。");
    return;
  }
  if (empty) empty.classList.add("hidden");
  if (content) content.classList.remove("hidden");
  await loadKnownDocuments();
  renderReportSectioned(content, meta, reportView.markdown);
}

export function exportCurrentReport() {
  if (!reportView.markdown) {
    showToast("还没有可导出的周报。", "err");
    return "";
  }
  const filename = reportExportFilename(reportView.meta);
  try {
    const blob = new Blob([reportView.markdown], { type: "text/markdown;charset=utf-8" });
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

function historyList(metas) {
  const list = el("report-history");
  if (!list) return;
  const items = Array.isArray(metas) ? metas : [];
  if (!items.length) {
    list.innerHTML = `<li class="dim">还没有生成过周报。</li>`;
    return;
  }
  list.innerHTML = "";
  items.forEach((meta) => {
    const id = meta.report_id || meta.digest_id;
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "report-item" + (id === reportView.reportId ? " selected" : "");
    button.dataset.reportId = id;
    if (id === reportView.reportId) button.setAttribute("aria-current", "true");
    const tmpl = document.createElement("span");
    tmpl.className = "report-item-template dim";
    tmpl.textContent = reportTemplateLabel(meta.template_id);
    const range = document.createElement("span");
    range.className = "report-item-range";
    range.textContent = (meta.range || {}).label || (meta.range || {}).from || "未知范围";
    const time = document.createElement("span");
    time.className = "report-item-time dim";
    time.textContent = `生成时间：${displayTime(meta.created_at)}`;
    const summary = document.createElement("span");
    summary.className = "report-item-summary dim";
    summary.textContent = reportHistorySummary(meta);
    button.appendChild(tmpl);
    button.appendChild(range);
    button.appendChild(time);
    button.appendChild(summary);
    button.addEventListener("click", () => { void openReport(id, meta.template_id); });
    item.appendChild(button);
    list.appendChild(item);
  });
}

async function loadReportHistory() {
  const list = el("report-history");
  if (!list) return [];
  try {
    // One history for both templates (shared digest boundary).
    const payload = await api("/api/digests");
    const metas = Array.isArray(payload && payload.digests) ? payload.digests : [];
    historyList(metas);
    return metas;
  } catch (e) {
    list.innerHTML = "";
    const item = document.createElement("li");
    item.className = "dim report-history-error";
    item.textContent = `历史周报加载失败：${e.message} `;
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "btn small";
    retry.textContent = "重试";
    retry.addEventListener("click", () => { void loadReportHistory(); });
    item.appendChild(retry);
    list.appendChild(item);
    return [];
  }
}

export async function openReport(reportId, template) {
  if (!reportId) return;
  reportView.reportId = reportId;
  setReportStatus("读取周报…");
  setReportActions([]);
  try {
    // Shared detail boundary for both templates.
    const payload = await api(`/api/digests/${encodeURIComponent(reportId)}`);
    const meta = payload.meta || null;
    await showReport(meta, payload.markdown || "");
    setReportStatus("");
    await loadReportHistory();
  } catch (e) {
    setReportStatus("读取失败：" + e.message, "error");
    setReportActions([
      { label: "重新读取", primary: true, run: () => openReport(reportId, template) },
      { label: "修改范围", run: () => { const node = el("report-range"); if (node) node.focus(); } },
    ]);
  }
}

async function generateReport() {
  const template = reportView.template;
  const legacy = template === LEGACY_TEMPLATE;
  const rangeNode = el("report-range");
  const payload = {
    template,
    range: rangeNode ? rangeNode.value : "this_week",
    force: !!(el("report-force") && el("report-force").checked),
  };
  if (payload.range === "custom") {
    payload.from = el("report-from") ? el("report-from").value : "";
    payload.to = el("report-to") ? el("report-to").value : "";
  }
  if (!legacy) {
    payload.modules = reportView.modules || [];
    payload.reporter = el("report-reporter") ? el("report-reporter").value : "";
    payload.report_date = el("report-date") ? el("report-date").value : "";
  }
  setReportBusy(true);
  setReportStatus("生成中…（同一指纹会直接复用缓存）");
  setReportActions([]);
  try {
    // Shared create boundary; the template picks the generator server-side.
    const result = await api("/api/digests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (result.status === "empty") {
      reportView.reportId = null;
      showReportEmpty(result.message || "该范围内没有材料。");
      setReportStatus(result.message || "该范围内没有材料。");
      setReportActions([
        { label: "修改范围", run: () => { const n = el("report-range"); if (n) n.focus(); } },
        { label: "再试一次", primary: true, run: generateReport },
      ]);
    } else {
      const report = result.report || result.digest || null;
      reportView.reportId = report ? (report.report_id || report.digest_id) : null;
      await showReport(report, result.markdown || "");
      setReportStatus(result.cached
        ? (result.rerendered ? "复用模型结果，已按新的汇报信息重渲染（未调用模型）。" : "命中缓存，未重新调用模型。")
        : "已生成并保存。");
      setReportActions([]);
    }
    await loadReportHistory();
  } catch (e) {
    setReportStatus("生成失败：" + e.message, "error");
    setReportActions([
      { label: "重试生成", primary: true, run: generateReport },
      { label: "修改范围", run: () => { const n = el("report-range"); if (n) n.focus(); } },
    ]);
    showToast("生成失败：" + e.message, "err");
  } finally {
    setReportBusy(false);
  }
}

export async function renderReportView() {
  const zone = el("report-zone");
  if (!zone) return;
  zone.classList.remove("hidden");
  setReportStatus("");
  setReportActions([]);
  updateReportCustomFields();
  updateTemplateVisibility();
  const select = el("report-template");
  if (select) reportView.template = select.value || RESEARCH_TEMPLATE;
  if (!reportView.templates.length) {
    try {
      await loadReportTemplates();
    } catch (e) {
      setReportStatus("模板加载失败：" + e.message, "error");
    }
  }
  updateTemplateVisibility();
  const metas = await loadReportHistory();
  if (metas.length && !reportView.reportId) {
    const first = metas[0];
    await openReport(first.report_id || first.digest_id, first.template_id);
  } else if (!metas.length) {
    showReportEmpty("还没有生成过周报。选择范围后点「生成科研周报」。");
    setReportActions([{ label: "生成科研周报", primary: true, run: generateReport }]);
  }
}

registerView("reports", renderReportView);

if (el("report-range")) {
  el("report-range").addEventListener("change", updateReportCustomFields);
  el("report-generate").addEventListener("click", generateReport);
  if (el("report-export")) el("report-export").addEventListener("click", exportCurrentReport);
  el("report-template").addEventListener("change", async (event) => {
    reportView.template = event.target.value;
    reportView.reportId = null;
    updateTemplateVisibility();
    await loadReportHistory();
  });
}
