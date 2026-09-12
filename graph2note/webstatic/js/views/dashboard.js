/* graph2note — read-only local telemetry dashboard (U1 relocation; A2 adds the
   weekly-digest block here, inside the dashboard zone). */
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { registerView } from "../router.js";
import { showToast } from "../ui.js";
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
    el.dashboardEmpty.querySelector("p").textContent = "数据看板加载失败。";
    el.dashboardEmpty.classList.remove("hidden");
    el.dashboardContent.classList.add("hidden");
    showToast("加载数据看板失败：" + e.message, "err");
  }
}

registerView("dashboard", renderDashboard);

/* ---------- Weekly digest (issue A2) ---------- */

function digestRangeLabel(meta) {
  const range = (meta && meta.range) || {};
  return range.label || `${range.from || "?"} ~ ${range.to || "?"}`;
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

function renderDigestHistory(metas) {
  if (!el.digestHistory) return;
  if (!metas.length) {
    el.digestHistory.innerHTML = `<li class="dim">还没有生成过小结。</li>`;
    return;
  }
  el.digestHistory.innerHTML = metas.map((meta) => {
    const usage = meta.usage || {};
    const tokens = usage.total_tokens != null ? `${usage.total_tokens} tokens` : "token 不可用";
    const selected = state.digestId === meta.digest_id ? "selected" : "";
    return `<li><button type="button" class="digest-item ${selected}" data-digest-id="${esc(meta.digest_id)}">
      <span class="digest-item-range">${esc(digestRangeLabel(meta))}</span>
      <span class="dim">${esc(meta.created_at || "")} · ${meta.document_count || 0} 篇 · ${esc(meta.model || "未知模型")} · ${esc(tokens)}</span>
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
    const metas = payload.digests || [];
    renderDigestHistory(metas);
    return metas;
  } catch (e) {
    el.digestHistory.innerHTML = `<li class="dim">历史小结加载失败。</li>`;
    return [];
  }
}

function showDigestMarkdown(meta, markdown) {
  let sources = "";
  if (meta && meta.document_ids && meta.document_ids.length) {
    const ids = meta.document_ids;
    sources = ids.length > 5
      ? ` · 来源：${ids.slice(0, 5).join("、")} 等 ${ids.length} 篇`
      : ` · 来源：${ids.join("、")}`;
  }
  el.digestViewerMeta.textContent = meta
    ? `${digestRangeLabel(meta)} · ${meta.document_count || 0} 篇 · 指纹 ${String(meta.fingerprint || "").slice(0, 12)}`
      + sources
    : "";
  if (markdown) {
    el.digestEmpty.classList.add("hidden");
    el.digestViewerContent.classList.remove("hidden");
    renderMarkdownInto(el.digestViewerContent, markdown);
  } else {
    el.digestViewerContent.classList.add("hidden");
    el.digestViewerContent.innerHTML = "";
    el.digestEmpty.classList.remove("hidden");
  }
}

async function openDigest(digestId) {
  if (!digestId) return;
  state.digestId = digestId;
  el.digestStatus.textContent = "读取小结…";
  try {
    const payload = await api(`/api/digests/${encodeURIComponent(digestId)}`);
    showDigestMarkdown(payload.meta || null, payload.markdown || "");
    el.digestStatus.textContent = "";
    await loadDigestHistory();
  } catch (e) {
    el.digestStatus.textContent = "读取失败：" + e.message;
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
  el.digestGenerate.disabled = true;
  el.digestStatus.textContent = "生成中…（同一指纹会直接复用缓存）";
  try {
    const r = await api("/api/digests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (r.status === "empty") {
      state.digestId = null;
      showDigestMarkdown(
        { range: r.range, document_count: 0, fingerprint: r.fingerprint, document_ids: [] },
        "",
      );
      setDigestEmpty(r.message || "该范围内没有材料。");
      el.digestStatus.textContent = r.message || "该范围内没有材料。";
    } else {
      state.digestId = r.digest ? r.digest.digest_id : null;
      showDigestMarkdown(r.digest || null, r.markdown || "");
      el.digestStatus.textContent = r.cached ? "命中缓存，未重新调用模型。" : "已生成并保存。";
    }
    await loadDigestHistory();
  } catch (e) {
    el.digestStatus.textContent = "生成失败：" + e.message;
  } finally {
    el.digestGenerate.disabled = false;
  }
}

async function renderDigestPanel() {
  if (!el.digestPanel) return;
  updateDigestCustomFields();
  const metas = await loadDigestHistory();
  if (metas.length && !state.digestId) {
    await openDigest(metas[0].digest_id);
  } else if (!metas.length) {
    showDigestMarkdown(null, "");
    setDigestEmpty("还没有生成过小结。选择范围后点「生成小结」。");
  }
}

if (el.digestRange) {
  el.digestRange.addEventListener("change", updateDigestCustomFields);
  el.digestGenerate.addEventListener("click", generateDigest);
}
