// Offline DOM behaviour test for the research weekly report view (issue 01).
//
// No browser, no network, no npm: a tiny DOM shim plus a scripted `fetch`
// replay drives the real `graph2note/webstatic/js/views/report.js` module.
// Run: node tests/report_view_dom.mjs
//
// Contract asserted:
//   * template list comes from `/api/report-templates` (科研周报 + 旧版小结);
//   * optional 专题 modules render with enable + ↑/↓ order and the exact config
//     is sent to the API (so the backend cache key matches what was generated);
//   * a generated research report renders sections in order with per-section
//     source links, deterministic stats + material budget and a generator badge;
//   * dead source ids are greyed and explain themselves; a cached result says so;
//   * a model failure keeps the last good report and offers retry;
//   * the legacy template delegates history/generation to `/api/digests` and
//     renders the whole Markdown (旧报告原样可读可导出);
//   * export downloads the exact Markdown snapshot.
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(here, "..", "graph2note", "webstatic", "js");

const delay = (ms = 5) => new Promise((resolve) => setTimeout(resolve, ms));
const escapeHtml = (value) => String(value == null ? "" : value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

/* ------------------------------------------------------------------ DOM shim */

function parseSelector(selector) {
  const spec = { tag: null, id: null, classes: [], attrs: [] };
  const token = String(selector).trim().split(/\s+/)[0] || "";
  const re = /\[([^\]]+)\]|([#.]?[A-Za-z0-9_-]+)/g;
  let m;
  while ((m = re.exec(token)) !== null) {
    if (m[1]) spec.attrs.push(m[1]);
    else if (m[2].startsWith("#")) spec.id = m[2].slice(1);
    else if (m[2].startsWith(".")) spec.classes.push(m[2].slice(1));
    else spec.tag = m[2].toLowerCase();
  }
  return spec;
}

function matchesSpec(node, spec) {
  if (spec.tag && node.tagName.toLowerCase() !== spec.tag) return false;
  if (spec.id && node.id !== spec.id) return false;
  if (spec.classes.some((c) => !node.classList.contains(c))) return false;
  if (spec.attrs.some((a) => node.getAttribute(a) == null)) return false;
  return true;
}

function collectDescendants(root) {
  const out = [];
  const walk = (node) => node.children.forEach((child) => { out.push(child); walk(child); });
  walk(root);
  return out;
}

const downloads = [];
const blobUrls = new Map();

function makeEl(tag = "div", id = null) {
  const listeners = new Map();
  const classes = new Set();
  const attrs = new Map();
  const el = {
    tagName: String(tag).toUpperCase(),
    _id: id,
    value: "",
    checked: false,
    textContent: "",
    disabled: false,
    href: "",
    download: "",
    title: "",
    type: "",
    dataset: {},
    style: {},
    children: [],
    parentNode: null,
    scrolled: 0,
    _html: "",
    classList: {
      add: (...c) => c.forEach((x) => classes.add(x)),
      remove: (...c) => c.forEach((x) => classes.delete(x)),
      contains: (c) => classes.has(c),
      toggle: (c, force) => {
        const on = force === undefined ? !classes.has(c) : Boolean(force);
        if (on) classes.add(c); else classes.delete(c);
        return on;
      },
    },
    setAttribute(k, v) {
      attrs.set(k, String(v));
      if (k === "id") el._id = String(v);
    },
    getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
    removeAttribute(k) { attrs.delete(k); },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    removeEventListener(type, fn) {
      const list = listeners.get(type) || [];
      const i = list.indexOf(fn);
      if (i >= 0) list.splice(i, 1);
    },
    dispatch(type, event = {}) {
      const base = { type, preventDefault() {}, stopPropagation() {} };
      for (const fn of [...(listeners.get(type) || [])]) fn({ ...base, ...event });
    },
    appendChild(child) {
      child.parentNode = el;
      el.children.push(child);
      return child;
    },
    removeChild(child) {
      const i = el.children.indexOf(child);
      if (i >= 0) el.children.splice(i, 1);
      if (child.parentNode === el) child.parentNode = null;
      return child;
    },
    insertBefore(node, ref) {
      const i = ref ? el.children.indexOf(ref) : -1;
      if (i < 0) el.children.push(node); else el.children.splice(i, 0, node);
      node.parentNode = el;
      return node;
    },
    focus() { globalThis.document.activeElement = el; },
    blur() { if (globalThis.document.activeElement === el) globalThis.document.activeElement = null; },
    click() {
      if (el.download) downloads.push({ filename: el.download, href: el.href });
      el.dispatch("click");
    },
    scrollIntoView() { el.scrolled += 1; },
    querySelector(selector) { return el.querySelectorAll(selector)[0] || null; },
    querySelectorAll(selector) {
      const spec = parseSelector(selector);
      return collectDescendants(el).filter((node) => matchesSpec(node, spec));
    },
  };
  Object.defineProperty(el, "id", {
    get() { return el._id; },
    set(v) { el._id = v == null ? null : String(v); },
  });
  Object.defineProperty(el, "className", {
    get() { return [...classes].join(" "); },
    set(v) {
      classes.clear();
      String(v || "").split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
    },
  });
  Object.defineProperty(el, "nextSibling", {
    get() {
      if (!el.parentNode) return null;
      const i = el.parentNode.children.indexOf(el);
      return el.parentNode.children[i + 1] || null;
    },
  });
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html || escapeHtml(el.textContent); },
    set(v) { el._html = String(v); el.children.length = 0; },
  });
  return el;
}

const elementCache = new Map();
const documentShim = {
  activeElement: null,
  body: makeEl("body"),
  createElement: (tag) => makeEl(tag),
  querySelector(selector) {
    if (!elementCache.has(selector)) {
      const id = selector.startsWith("#") ? selector.slice(1) : null;
      elementCache.set(selector, makeEl("div", id));
    }
    return elementCache.get(selector);
  },
  querySelectorAll: () => [],
  getElementById(id) { return documentShim.querySelector(`#${id}`); },
  addEventListener(type, fn) { documentShim._listeners.push({ type, fn }); },
  dispatch(type, event = {}) {
    const base = { type, preventDefault() {}, stopPropagation() {} };
    for (const { type: t, fn } of [...documentShim._listeners]) if (t === type) fn({ ...base, ...event });
  },
  _listeners: [],
};

globalThis.document = documentShim;
globalThis.localStorage = {
  _data: new Map(),
  getItem(k) { return this._data.has(k) ? this._data.get(k) : null; },
  setItem(k, v) { this._data.set(k, String(v)); },
  removeItem(k) { this._data.delete(k); },
};
globalThis.window = {
  addEventListener() {},
  marked: { parse: (md) => `<div class="md">${escapeHtml(md)}</div>` },
  __mdMissing: false,
};
globalThis.location = { hash: "#reports" };
globalThis.Blob = class Blob {
  constructor(parts, options) { this.parts = parts; this.type = (options || {}).type; }
};
let blobSeq = 0;
globalThis.URL.createObjectURL = (blob) => {
  const url = `blob:test/${++blobSeq}`;
  blobUrls.set(url, blob);
  return url;
};
globalThis.URL.revokeObjectURL = () => {};

const el = (selector) => documentShim.querySelector(selector);

/* ------------------------------------------------------------- fetch replay */

const calls = [];
let reportList = [];
let digestList = [];
let researchPost = null;
let digestPost = null;
let listFails = false;

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: { get: () => "application/json" },
    json: async () => JSON.parse(JSON.stringify(body)),
    blob: async () => body,
  };
}

const TEMPLATES = {
  templates: [
    { id: "research_weekly", version: "1", label: "科研周报", schema_version: 1, supports_modules: true },
    { id: "weekly_summary", version: "2", label: "旧版四节小结", schema_version: 2, supports_modules: false, legacy: true },
  ],
  modules: [
    { key: "experiments", title: "实验结果" },
    { key: "process", title: "过程记录" },
    { key: "method", title: "方法备忘" },
  ],
};

globalThis.fetch = async (url, opts = {}) => {
  const route = String(url);
  const method = (opts.method || "GET").toUpperCase();
  calls.push({ route, method, body: opts.body ? JSON.parse(opts.body) : null });
  if (route === "/api/documents" && method === "GET") {
    return jsonResponse([
      { document_id: "doc-a", title: "线性代数讲义" },
      { document_id: "doc-b", title: "微分方程笔记" },
    ]);
  }
  if (route === "/api/report-templates" && method === "GET") {
    return jsonResponse(TEMPLATES);
  }
  if (route === "/api/reports" && method === "GET") {
    if (listFails) return jsonResponse({ detail: "历史读取失败" }, 500);
    return jsonResponse({ reports: reportList, total: reportList.length });
  }
  if (route === "/api/reports" && method === "POST") {
    if (!researchPost) throw new Error("no POST handler configured");
    return researchPost();
  }
  const singleReport = /^\/api\/reports\/(.+)$/.exec(route);
  if (singleReport && method === "GET") {
    return jsonResponse({ meta: RESEARCH_META, markdown: RESEARCH_MARKDOWN, sections: RESEARCH_META.sections });
  }
  if (route === "/api/digests" && method === "GET") {
    return jsonResponse({ digests: digestList, total: digestList.length });
  }
  if (route === "/api/digests" && method === "POST") {
    if (!digestPost) throw new Error("no POST handler configured");
    return digestPost();
  }
  const singleDigest = /^\/api\/digests\/(.+)$/.exec(route);
  if (singleDigest && method === "GET") {
    return jsonResponse({ meta: LEGACY_META, markdown: LEGACY_MARKDOWN, sections: LEGACY_META.sections });
  }
  throw new Error(`unexpected fetch ${method} ${route}`);
};

/* ----------------------------------------------------------------- fixtures */

const RESEARCH_META = {
  report_id: "rp-2026-09-15-abc",
  created_at: "2026-09-15T10:30:00",
  template_id: "research_weekly",
  template_version: "1",
  schema_version: 1,
  prompt_version: "research-report-sections-1",
  range: { kind: "last_week", from: "2026-09-08", to: "2026-09-14", label: "上周（2026-09-08 ~ 2026-09-14）" },
  fingerprint: "abcdef0123456789",
  reporter: "张三",
  report_date: "2026-09-13",
  document_count: 2,
  document_ids: ["doc-a", "doc-b"],
  modules: [
    { key: "process", title: "过程记录", enabled: true },
    { key: "experiments", title: "实验结果", enabled: false },
  ],
  llm_mode: "json",
  model: "kimi-k3",
  llm_calls: 1,
  usage: { prompt_tokens: 1200, completion_tokens: 800, total_tokens: 2000 },
  stats: {
    document_count: 3, new_document_count: 1, parsed_count: 2, failed_count: 1,
    topic_count: 2, tag_count: 3,
  },
  budget: { max_docs: 60, topic_floor: 2, total: 3, kept: 2, omitted: 1 },
  sections: [
    { key: "overview", title: "本周概览", source_document_ids: ["doc-a"], generated_by: "model", chars: 20 },
    { key: "progress", title: "本周进展", source_document_ids: ["doc-a", "doc-b"], generated_by: "model", chars: 30 },
    { key: "issues", title: "问题与求助", source_document_ids: [], generated_by: "model", chars: 0 },
    { key: "process", title: "过程记录", source_document_ids: ["doc-b"], generated_by: "model", chars: 12 },
    { key: "appendix", title: "附录：来源材料", source_document_ids: ["doc-a", "doc-b", "doc-zzz"], generated_by: "deterministic", chars: 40 },
  ],
};

const RESEARCH_MARKDOWN = [
  "# 科研周报",
  "时间范围：上周（2026-09-08 ~ 2026-09-14）",
  "汇报人：张三　　2026-09-13",
  "",
  "## 本周概览",
  "主线：编码推导。",
  "",
  "## 本周进展",
  "（一）信道编码",
  "- 已知：完成步骤",
  "",
  "## 问题与求助",
  "_（本节暂无内容）_",
  "",
  "## 过程记录",
  "记录过程与踩坑。",
  "",
  "## 附录：来源材料",
  "- [线性代数讲义](#doc/doc-a)",
  "",
].join("\n");

const LEGACY_META = {
  digest_id: "dg-legacy-1",
  created_at: "2026-09-08T10:00:00",
  range: { label: "旧版范围" },
  fingerprint: "111222333444",
  document_count: 1,
  document_ids: ["doc-a"],
  model: "glm-5",
  llm_calls: 0,
  usage: {},
  sections: [
    { key: "overview", title: "本周概览", source_document_ids: ["doc-a"] },
  ],
};

const LEGACY_MARKDOWN = "# 本周小结\n\n## 本周概览\n旧版整篇渲染正文。\n";

/* ------------------------------------------------------------- module import */

const reportView = await import(pathToFileURL(path.join(JS, "views", "report.js")).href);

/* --------------------------------------------------- 1) pure contract helpers */

assert.strictEqual(reportView.reportTemplateLabel("research_weekly"), "科研周报");
assert.strictEqual(reportView.reportTemplateLabel("weekly_summary"), "旧版四节小结");
assert.strictEqual(reportView.reportSectionAnchor("process"), "report-section-process");
assert.strictEqual(reportView.reportSectionAnchor("weird key!"), "report-section-weird-key-");

const parsed = reportView.splitReportMarkdown(RESEARCH_MARKDOWN, RESEARCH_META.sections);
assert.deepStrictEqual(parsed.sections.map((s) => s.key),
  ["overview", "progress", "issues", "process", "appendix"], "markdown order follows meta.sections");
assert.ok(parsed.lead.includes("汇报人：张三"), "lead keeps the reporter line");
assert.strictEqual(parsed.sections[2].body, "_（本节暂无内容）_", "title-only issues section still renders");

const merged = reportView.normalizeModuleConfig(TEMPLATES.modules, [
  { key: "process", enabled: true },
]);
assert.deepStrictEqual(merged.map((m) => `${m.key}:${m.enabled}`),
  ["process:true", "experiments:false", "method:false"], "saved config wins order; catalog appended disabled");

const stats = reportView.reportStatsSummary(RESEARCH_META);
assert.ok(stats.some((c) => c.label === "范围内" && c.value === "3 篇"));
assert.ok(stats.some((c) => c.label === "选入材料" && c.value === "2 篇"));
assert.ok(reportView.reportBudgetSummary(RESEARCH_META).includes("省略 1 篇"));
assert.ok(reportView.reportMetaSummary(RESEARCH_META).includes("科研周报"));
assert.ok(reportView.reportMetaSummary(RESEARCH_META).includes("v1"));
assert.strictEqual(
  reportView.reportExportFilename(RESEARCH_META),
  "research-weekly_2026-09-08_2026-09-14_2026-09-15.md",
);
assert.strictEqual(
  reportView.reportExportFilename({ ...LEGACY_META, template_id: "weekly_summary", range: { from: "2026-09-01", to: "2026-09-07" } }),
  "weekly-summary_2026-09-01_2026-09-07_2026-09-08.md",
);

/* ---------------------------------------- 2) first run: templates + empty state */

const viewerContent = el("#report-viewer-content");
const zone = el("#report-zone");
reportList = [];
await reportView.renderReportView();
assert.strictEqual(zone.classList.contains("hidden"), false, "report zone shown");
assert.strictEqual(el("#report-template").children.length, 2, "template selector filled from the API");
assert.deepStrictEqual(el("#report-template").children.map((o) => o.textContent),
  ["科研周报 (v1)", "旧版四节小结 (v2)"]);
assert.strictEqual(el("#report-module-list").children.length, 3, "module catalog rendered");
assert.strictEqual(el("#report-empty").textContent.includes("还没有生成过周报"), true);
const firstRunActions = el("#report-actions").children.map((n) => n.textContent);
assert.deepStrictEqual(firstRunActions, ["生成科研周报"]);

/* ---------------------------------- 3) module config: enable + ↑ reorder → POST */

const moduleItems = () => el("#report-module-list").children;
const moduleByKey = (key) => moduleItems().find((li) => li.dataset.moduleKey === key);
const experimentToggle = moduleByKey("experiments").querySelector("input.report-module-enabled");
experimentToggle.checked = true;
experimentToggle.dispatch("change");
assert.strictEqual(moduleByKey("experiments")
  .querySelector("input.report-module-enabled").checked, true, "enable toggles the module");
moduleByKey("experiments").querySelector("button.report-module-up").click();
const orderAfterMove = moduleItems().map((li) => li.dataset.moduleKey);
assert.strictEqual(orderAfterMove[0], "experiments", "↑ moves the module to the front");
assert.ok(JSON.parse(globalThis.localStorage.getItem("graph2note.report.modules"))[0].key === "experiments",
  "module config is persisted for the next visit");

researchPost = () => jsonResponse({
  status: "ok", generated: true, cached: false, llm_calls: 1,
  report: RESEARCH_META, markdown: RESEARCH_MARKDOWN, sections: RESEARCH_META.sections,
});
reportList = [RESEARCH_META];
el("#report-generate").click();
await delay(30);
const post = calls.filter((c) => c.route === "/api/reports" && c.method === "POST").pop();
assert.ok(post, "generate posts to /api/reports");
assert.deepStrictEqual(post.body.modules.map((m) => `${m.key}:${m.enabled}`),
  ["experiments:true", "process:false", "method:false"], "the exact module config is sent");

/* ------------------------------------------ 4) sectioned render + provenance */

const sections = () => viewerContent.querySelectorAll("section.report-section");
assert.strictEqual(sections().length, 5, "five sections rendered");
assert.deepStrictEqual(sections().map((s) => s.getAttribute("data-section")),
  ["overview", "progress", "issues", "process", "appendix"]);
const sectionByKey = (key) => viewerContent.querySelector(`#report-section-${key}`);
assert.ok(sectionByKey("progress").children[0].textContent === "本周进展");
assert.ok(sectionByKey("progress").querySelector(".report-section-body").innerHTML.includes("信道编码"), "section body markdown rendered");
assert.strictEqual(sectionByKey("appendix").querySelector(".report-section-title").textContent, "附录：来源材料", "appendix rendered");
assert.ok(el("#report-viewer-meta").textContent.includes("生成方式：模型分节"), "llm mode visible");
assert.ok(viewerContent.querySelector(".report-stats"), "stats strip rendered");
assert.ok(viewerContent.querySelector(".report-budget-note").textContent.includes("材料预算"), "budget visible");

const navLabels = viewerContent.querySelectorAll("button.report-nav-link").map((b) => b.textContent);
assert.deepStrictEqual(navLabels, ["本周概览", "本周进展", "问题与求助", "过程记录", "附录：来源材料"]);
viewerContent.querySelectorAll("button.report-nav-link")[1].click();
assert.strictEqual(sectionByKey("progress").scrolled, 1, "nav scrolls to the section");

const progressSources = sectionByKey("progress").querySelectorAll(".report-source");
assert.strictEqual(progressSources[0].tagName, "A", "known source renders as a link");
assert.strictEqual(progressSources[0].href, "#doc/doc-a");
assert.strictEqual(progressSources[0].textContent, "线性代数讲义");
const appendixSources = sectionByKey("appendix").querySelectorAll(".report-source");
const dead = appendixSources.find((n) => n.classList.contains("report-source-missing"));
assert.ok(dead, "unknown source id is greyed out");
dead.click();
assert.ok(el("#toast").textContent.includes("doc-zzz"), "dead source explains itself");

/* -------------------------------------------------- 5) export the snapshot */

assert.strictEqual(el("#report-export").disabled, false, "export enabled once a report is loaded");
el("#report-export").click();
assert.strictEqual(downloads.length, 1, "export triggered one download");
assert.strictEqual(downloads[0].filename, "research-weekly_2026-09-08_2026-09-14_2026-09-15.md");
assert.strictEqual(blobUrls.get(downloads[0].href).parts[0], RESEARCH_MARKDOWN, "blob carries the markdown");

/* ------------------------------------------ 6) cached + failure states */

researchPost = () => jsonResponse({
  status: "ok", generated: false, cached: true, llm_calls: 0,
  report: RESEARCH_META, markdown: RESEARCH_MARKDOWN, sections: RESEARCH_META.sections,
});
el("#report-generate").click();
await delay(30);
assert.ok(el("#report-status").textContent.includes("命中缓存"), "cache hit is reported");

const goodSection = sectionByKey("overview");
researchPost = () => jsonResponse({ detail: "模型超时" }, 502);
el("#report-generate").click();
await delay(30);
assert.ok(el("#report-status").textContent.includes("生成失败：模型超时"), "failure message explicit");
assert.ok(el("#report-status").className.includes("report-status-error"), "failure state styled");
assert.deepStrictEqual(el("#report-actions").children.map((n) => n.textContent),
  ["重试生成", "修改范围"], "failure offers retry + range change");
assert.ok(sectionByKey("overview") === goodSection, "failed generation keeps the last good report");

/* the empty state keeps 修改范围 / 再试一次 */
researchPost = () => jsonResponse({ status: "empty", range: { label: "本周" }, message: "该范围内没有材料。" });
el("#report-generate").click();
await delay(30);
assert.ok(el("#report-empty").textContent.includes("没有材料"));
assert.deepStrictEqual(el("#report-actions").children.map((n) => n.textContent),
  ["修改范围", "再试一次"]);

/* ---------------------------------- 7) legacy template: read + generate path */

el("#report-template").value = "weekly_summary";
el("#report-template").dispatch("change", { target: el("#report-template") });
await delay(10);
assert.strictEqual(el("#report-modules").classList.contains("hidden"), true, "legacy template hides 专题");
digestList = [LEGACY_META];
await reportView.renderReportView();
const legacyHistory = el("#report-history").querySelectorAll("button.report-item");
assert.strictEqual(legacyHistory.length, 1, "legacy history comes from /api/digests");
assert.ok(legacyHistory[0].children.map((c) => c.textContent).join(" ").includes("旧版范围"),
  "legacy history label readable");
digestPost = () => jsonResponse({
  status: "ok", cached: false, digest: LEGACY_META, markdown: LEGACY_MARKDOWN,
  sections: LEGACY_META.sections,
});
el("#report-generate").click();
await delay(30);
const legacyPost = calls.filter((c) => c.route === "/api/digests" && c.method === "POST").pop();
assert.ok(legacyPost, "legacy template posts to /api/digests");
assert.strictEqual(legacyPost.body.modules, undefined, "legacy request carries no module config");
assert.ok(viewerContent.querySelector(".report-section-body").innerHTML.includes("旧版整篇渲染正文"), "legacy markdown rendered whole");

console.log("report_view_dom: all assertions passed ✓");
process.exit(0);
