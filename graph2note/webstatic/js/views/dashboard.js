/* graph2note — read-only local telemetry dashboard (U1 relocation; A2 will add
   the weekly-digest block, not this issue). */
"use strict";

import { el } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { registerView } from "../router.js";
import { showToast } from "../ui.js";

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
