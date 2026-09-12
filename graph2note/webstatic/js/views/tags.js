/* graph2note — tag vocabulary view (moved out of Library by U1; same
   governance behaviour: rename / merge / create).

   auto-organization issue 01 adds the 「整理建议」 review loop on top of the
   existing per-tag governance: the vocab is rendered by persisted theme groups
   (schema v2), and the LLM plan is shown for per-merge / per-group accept or
   reject before a deterministic apply.  Pure render helpers are exported so the
   offline Node contract test can exercise them without a browser. */
"use strict";

import { el } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { registerView } from "../router.js";
import { showViewError, clearViewError, showToast } from "../ui.js";

const ORGANIZE = {
  plan: null,
  merges: new Set(),
  groups: new Set(),
};

function tagRow(item, escape) {
  const aliases = item.aliases && item.aliases.length
    ? ` · 别名：${escape(item.aliases.join("、"))}` : "";
  return `<span class="tag-vocabulary-item">
      <span class="tag-name">#${escape(item.tag)}</span>
      <span class="dim">${item.count} 份${aliases}</span>
      <button class="tag-action" data-tag-action="rename" data-tag="${escape(item.tag)}">重命名</button>
      <button class="tag-action" data-tag-action="merge" data-tag="${escape(item.tag)}">合并</button>
    </span>`;
}

/* Grouped vocabulary: persisted groups first, then the ungrouped remainder. */
export function structureHtml(structure, escape) {
  const groups = (structure && structure.groups) || [];
  const ungrouped = (structure && structure.ungrouped) || [];
  const parts = [
    `<div class="tag-organize-bar">
      <button class="btn small" data-organize-action="plan">整理建议</button>
      <span class="dim">LLM 审计整个词表，建议合并与主题分组；逐条确认后应用。</span>
    </div>`,
  ];
  if (groups.length) {
    parts.push('<div class="tag-groups">');
    for (const group of groups) {
      parts.push(`<section class="tag-group" data-tag-group="${escape(group.name)}">
        <h4 class="tag-group-head">${escape(group.name)} <span class="dim">${group.size} 个标签</span></h4>
        <div class="tag-group-body">${group.tags.map((item) => tagRow(item, escape)).join("")}</div>
      </section>`);
    }
    parts.push("</div>");
  }
  if (ungrouped.length) {
    parts.push(`<section class="tag-group tag-group-ungrouped" data-tag-group="">
      <h4 class="tag-group-head">未分组 <span class="dim">${ungrouped.length} 个标签</span></h4>
      <div class="tag-group-body">${ungrouped.map((item) => tagRow(item, escape)).join("")}</div>
    </section>`);
  }
  if (!groups.length && !ungrouped.length) {
    parts.push('<span class="dim">暂无标签，打开文档后可添加。</span>');
  }
  return parts.join("");
}

/* Review panel: accept/reject each merge pair; accept/reject each theme group. */
export function organizePlanHtml(view, escape) {
  const plan = (view && view.plan) || { merges: [], groups: [] };
  const merges = plan.merges || [];
  const groups = plan.groups || [];
  const mergeRows = merges.map((merge) => `
    <label class="tag-merge-row" data-organize-merge-row="${escape(merge.source)}">
      <input type="checkbox" data-organize-merge="${escape(merge.source)}" ${view.merges.has(merge.source) ? "checked" : ""}>
      <span class="tag-name">#${escape(merge.source)}</span>
      <span class="dim">→</span>
      <span class="tag-name">#${escape(merge.target)}</span>
      <span class="dim">${merge.source_count} → ${merge.target_count} 份${merge.reason ? ` · ${escape(merge.reason)}` : ""}</span>
    </label>`).join("");
  const groupRows = groups.map((group) => `
    <label class="tag-organize-group" data-organize-group-row="${escape(group.name)}">
      <input type="checkbox" data-organize-group="${escape(group.name)}" ${view.groups.has(group.name) ? "checked" : ""}>
      <strong>${escape(group.name)}</strong>
      <span class="dim">${group.size} 个：${group.tags.map((item) => escape(item.tag)).join("、")}</span>
    </label>`).join("");
  return `<div class="tag-organize-panel" data-organize-panel="1">
    <div class="tag-organize-head">
      <h3>整理建议</h3>
      <p class="dim">合并 ${merges.length} 对 · 分组 ${groups.length} 组 · 预估调用 1 次</p>
      <div class="tag-organize-actions">
        <button class="btn small" data-organize-action="accept-all">全部接受</button>
        <button class="btn small" data-organize-action="apply">应用所选</button>
        <button class="btn small" data-organize-action="cancel">取消</button>
      </div>
    </div>
    ${merges.length ? `<h4>合并建议</h4><div class="tag-merge-list">${mergeRows}</div>` : ""}
    ${groups.length ? `<h4>主题分组</h4><div class="tag-group-list">${groupRows}</div>` : ""}
  </div>`;
}

/* The accepted subset posted to the apply endpoint: merge sources + group names. */
export function acceptedSelection(plan, mergeSources, groupNames) {
  return {
    merges: ((plan && plan.merges) || [])
      .filter((merge) => mergeSources.has(merge.source)).map((merge) => merge.source),
    groups: ((plan && plan.groups) || [])
      .filter((group) => groupNames.has(group.name)).map((group) => group.name),
  };
}

/* ------------------------------------------------------------------ wiring */

function jsonPost(route, body) {
  return api(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function wireVocabularyActions() {
  el.tagList.querySelectorAll("button[data-tag-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = button.dataset.tag;
      const target = window.prompt(
        button.dataset.tagAction === "merge" ? "合并到哪个标签？" : "重命名为？", source);
      if (!target || target === source) return;
      try {
        await jsonPost(`/api/tags/${button.dataset.tagAction}`, { source, target });
        await renderTagVocabulary();
        showToast(button.dataset.tagAction === "merge" ? "标签已合并" : "标签已重命名", "ok");
      } catch (e) { showToast("标签治理失败：" + e.message, "err"); }
    });
  });
  el.tagList.querySelectorAll("button[data-organize-action]").forEach((button) => {
    if (button.dataset.organizeAction === "plan") {
      button.addEventListener("click", (event) => { event.preventDefault(); openOrganizePlan(); });
    }
  });
}

export async function renderTagVocabulary() {
  clearViewError(el.tagsZone);
  if (!el.tagList) return;
  let structure;
  try {
    structure = await api("/api/tags/groups");
  } catch (e) {
    showViewError(el.tagsZone, "加载标签词表失败：" + e.message, renderTagVocabulary);
    return;
  }
  ORGANIZE.plan = null;
  el.tagList.innerHTML = structureHtml(structure, esc);
  wireVocabularyActions();
}

async function openOrganizePlan() {
  let plan;
  try {
    plan = await jsonPost("/api/tags/organize/plan", {});
  } catch (e) {
    showToast("生成整理建议失败：" + e.message, "err");
    return;
  }
  ORGANIZE.plan = plan;
  ORGANIZE.merges = new Set(((plan && plan.merges) || []).map((merge) => merge.source));
  ORGANIZE.groups = new Set(((plan && plan.groups) || []).map((group) => group.name));
  renderOrganizePlan();
}

function renderOrganizePlan() {
  el.tagList.innerHTML = organizePlanHtml(ORGANIZE, esc);
  el.tagList.querySelectorAll("button[data-organize-action]").forEach((button) => {
    const action = button.dataset.organizeAction;
    if (action === "accept-all") {
      button.addEventListener("click", () => {
        ORGANIZE.merges = new Set((ORGANIZE.plan.merges || []).map((m) => m.source));
        ORGANIZE.groups = new Set((ORGANIZE.plan.groups || []).map((g) => g.name));
        renderOrganizePlan();
      });
    } else if (action === "apply") {
      button.addEventListener("click", applyOrganize);
    } else if (action === "cancel") {
      button.addEventListener("click", () => { renderTagVocabulary(); });
    }
  });
  el.tagList.querySelectorAll("input[data-organize-merge]").forEach((box) => {
    box.addEventListener("change", () => {
      if (box.checked) ORGANIZE.merges.add(box.dataset.organizeMerge);
      else ORGANIZE.merges.delete(box.dataset.organizeMerge);
    });
  });
  el.tagList.querySelectorAll("input[data-organize-group]").forEach((box) => {
    box.addEventListener("change", () => {
      if (box.checked) ORGANIZE.groups.add(box.dataset.organizeGroup);
      else ORGANIZE.groups.delete(box.dataset.organizeGroup);
    });
  });
}

async function applyOrganize() {
  const accepted = acceptedSelection(ORGANIZE.plan, ORGANIZE.merges, ORGANIZE.groups);
  try {
    await jsonPost("/api/tags/organize/apply", {
      plan_id: ORGANIZE.plan.plan_id, accepted,
    });
  } catch (e) { showToast("应用整理建议失败：" + e.message, "err"); return; }
  await renderTagVocabulary();
  showToast("整理建议已应用", "ok");
}

function renderTags() {
  el.tagsZone.classList.remove("hidden");
  renderTagVocabulary();
}

el.tagCreateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = el.tagCreateInput.value.trim();
  if (!value) return;
  try {
    await jsonPost("/api/tags", { tag: value });
    el.tagCreateInput.value = "";
    await renderTagVocabulary();
  } catch (e) { showToast("新增标签失败：" + e.message, "err"); }
});

registerView("tags", renderTags);
