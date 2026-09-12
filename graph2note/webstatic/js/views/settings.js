/* graph2note — LLM provider/model settings (U1 relocation; A3 will extend the
   custom-provider section inside this view). */
"use strict";

import { el, state } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { registerView } from "../router.js";
import { showViewError, clearViewError, showToast } from "../ui.js";

function llmStatusText(status) {
  return {
    available: "可用",
    missing_credentials: "未配置凭证",
    auth_failed: "认证失败",
    request_failed: "请求失败",
  }[status] || "未检测";
}

function llmStatusClass(status) {
  return status ? `llm-status ${esc(status)}` : "llm-status";
}

function updateLlmModelOptions(row, selected) {
  const providerId = row.querySelector(".llm-provider").value;
  const purpose = row.dataset.purpose;
  const provider = (state.llmSettings.providers || []).find((item) => item.id === providerId);
  const models = provider && provider.capabilities[purpose]
    ? provider.capabilities[purpose].models || [] : [];
  const select = row.querySelector(".llm-model");
  select.innerHTML = models.map((model) =>
    `<option value="${esc(model)}">${esc(model)}</option>`).join("");
  if (models.includes(selected)) select.value = selected;
}

function renderLlmChannels(snapshot) {
  const providers = snapshot.providers || [];
  el.llmProviderList.innerHTML = providers.map((provider) => `
    <div class="llm-provider-card">
      <span>${esc(provider.name)}</span>
      <span class="dim">${provider.kind === "custom" ? "自定义 · " : ""}${provider.credential_configured ? "凭证已配置" : "未配置凭证"}</span>
    </div>`).join("");
  el.llmChannelList.innerHTML = (snapshot.purposes || []).map((purpose) => {
    const current = snapshot.channels[purpose];
    const label = (snapshot.purpose_labels || {})[purpose] || purpose;
    const options = providers.map((provider) =>
      `<option value="${esc(provider.id)}"${provider.id === current.provider ? " selected" : ""}>${esc(provider.name)}</option>`
    ).join("");
    return `<div class="llm-channel-row" data-purpose="${esc(purpose)}">
      <div class="llm-channel-label"><strong>${esc(label)}</strong><span class="dim">${esc(purpose)}</span></div>
      <select class="llm-provider" aria-label="${esc(label)}供应商">${options}</select>
      <select class="llm-model" aria-label="${esc(label)}模型"></select>
      <span class="llm-status">未检测</span>
    </div>`;
  }).join("");
  el.llmChannelList.querySelectorAll(".llm-channel-row").forEach((row) => {
    const current = snapshot.channels[row.dataset.purpose];
    updateLlmModelOptions(row, current && current.model);
    row.querySelector(".llm-provider").addEventListener("change", () => updateLlmModelOptions(row));
  });
  renderLlmCustom(snapshot);
}

function renderLlmHealth(payload) {
  const statuses = payload.statuses || {};
  el.llmHealthList.innerHTML = (state.llmSettings.purposes || []).map((purpose) => {
    const item = statuses[purpose] || {};
    const label = state.llmSettings.purpose_labels[purpose] || purpose;
    const detail = item.detail ? ` · ${esc(item.detail)}` : "";
    const status = item.status || "not_checked";
    const row = Array.from(el.llmChannelList.querySelectorAll(".llm-channel-row"))
      .find((candidate) => candidate.dataset.purpose === purpose);
    if (row) {
      const badge = row.querySelector(".llm-status");
      badge.className = llmStatusClass(status);
      badge.textContent = llmStatusText(status);
    }
    return `<div class="llm-health-item"><strong>${esc(label)}</strong><span class="${llmStatusClass(status)}">${llmStatusText(status)}</span><span class="dim">${esc(item.provider || "")}/${esc(item.model || "")}${detail}</span></div>`;
  }).join("");
}

async function renderLlmSettings() {
  clearViewError(el.settingsZone);
  el.settingsZone.classList.remove("hidden");
  el.llmChannelList.innerHTML = "<p class=\"dim\">加载配置中…</p>";
  resetLlmCustomForm();
  try {
    state.llmSettings = await api("/api/llm/settings");
    renderLlmChannels(state.llmSettings);
    el.llmHealthList.innerHTML = "<p class=\"dim\">尚未检测通道可用性。</p>";
  } catch (e) {
    el.llmChannelList.innerHTML = "";
    showViewError(el.settingsZone, "加载 LLM 设置失败：" + e.message, renderLlmSettings);
  }
}

async function saveLlmSettings() {
  if (!state.llmSettings) return;
  const channels = {};
  el.llmChannelList.querySelectorAll(".llm-channel-row").forEach((row) => {
    channels[row.dataset.purpose] = {
      provider: row.querySelector(".llm-provider").value,
      model: row.querySelector(".llm-model").value,
    };
  });
  try {
    state.llmSettings = await api("/api/llm/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channels }),
    });
    renderLlmChannels(state.llmSettings);
    showToast("LLM 配置已保存，下一次任务生效", "ok");
  } catch (e) { showToast("保存 LLM 配置失败：" + e.message, "err"); }
}

async function checkLlmHealth() {
  el.llmHealthButton.disabled = true;
  el.llmHealthButton.textContent = "检测中…";
  try {
    renderLlmHealth(await api("/api/llm/health", { method: "POST" }));
  } catch (e) { showToast("检测 LLM 通道失败：" + e.message, "err"); }
  el.llmHealthButton.disabled = false;
  el.llmHealthButton.textContent = "检测可用性";
}

el.llmSaveButton.addEventListener("click", saveLlmSettings);
el.llmHealthButton.addEventListener("click", checkLlmHealth);

/* ---------- Custom OpenAI-compatible providers (issue A3) ---------- */

function customProviderHint(extra) {
  el.llmCustomHint.textContent = extra || "";
}

function resetLlmCustomForm() {
  el.llmCustomForm.reset();
  el.llmCustomId.value = "";
  el.llmCustomSubmit.textContent = "添加供应商";
  el.llmCustomCancel.classList.add("hidden");
  customProviderHint("");
}

function renderLlmCustom(snapshot) {
  const providers = (snapshot && snapshot.custom_providers) || [];
  if (!providers.length) {
    el.llmCustomList.innerHTML = '<p class="dim">尚未添加自定义供应商。</p>';
    return;
  }
  el.llmCustomList.innerHTML = providers.map((provider) => `
    <div class="llm-custom-card" data-provider="${esc(provider.id)}">
      <div class="llm-custom-info">
        <strong>${esc(provider.name)}</strong>
        <span class="dim">${esc(provider.base_url)}</span>
        <span class="dim">模型：${esc((provider.models || []).join(", ") || "—")}</span>
        <span class="llm-status ${provider.credential_configured ? "available" : "missing_credentials"}">${provider.credential_configured ? "Key 已设置" : "未设置 Key"}</span>
      </div>
      <div class="llm-custom-actions">
        <button type="button" class="btn small" data-action="edit">编辑</button>
        <button type="button" class="btn small" data-action="models">拉取模型</button>
        <button type="button" class="btn small" data-action="delete">删除</button>
      </div>
    </div>`).join("");
  el.llmCustomList.querySelectorAll(".llm-custom-card").forEach((card) => {
    card.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", () => handleLlmCustomAction(card.dataset.provider, button.dataset.action, button));
    });
  });
}

function handleLlmCustomAction(providerId, action, button) {
  const provider = ((state.llmSettings || {}).custom_providers || [])
    .find((item) => item.id === providerId);
  if (!provider) return;
  if (action === "edit") {
    el.llmCustomId.value = provider.id;
    el.llmCustomName.value = provider.name;
    el.llmCustomBase.value = provider.base_url;
    el.llmCustomKey.value = "";
    el.llmCustomModels.value = (provider.models || []).join("\n");
    el.llmCustomSubmit.textContent = "保存供应商";
    el.llmCustomCancel.classList.remove("hidden");
    customProviderHint(provider.credential_configured
      ? "API Key 已设置；留空则保持原 Key 不变。"
      : "尚未设置 API Key。");
    el.llmCustomName.focus();
    return;
  }
  if (action === "delete") {
    if (!window.confirm(`删除自定义供应商「${provider.name}」？其用途指派将回退默认。`)) return;
    requestLlmCustom("DELETE", `/api/llm/providers/${encodeURIComponent(providerId)}`);
    return;
  }
  if (action === "models") {
    button.disabled = true;
    requestLlmCustom("POST", `/api/llm/providers/${encodeURIComponent(providerId)}/models`,
      undefined, button);
  }
}

async function requestLlmCustom(method, route, body, button) {
  try {
    const payload = await api(route, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    state.llmSettings = payload;
    renderLlmChannels(payload);
    renderLlmCustom(payload);
    resetLlmCustomForm();
    el.llmHealthList.innerHTML = '<p class="dim">尚未检测通道可用性。</p>';
    showToast(payload.notice || "已保存自定义供应商", "ok");
  } catch (e) {
    showToast("自定义供应商操作失败：" + e.message, "err");
  } finally {
    if (button) button.disabled = false;
  }
}

function submitLlmCustom(event) {
  event.preventDefault();
  const name = el.llmCustomName.value.trim();
  const baseUrl = el.llmCustomBase.value.trim();
  const apiKey = el.llmCustomKey.value.trim();
  const models = el.llmCustomModels.value;
  if (!name || !baseUrl) { customProviderHint("名称与 Base URL 必填"); return; }
  const providerId = el.llmCustomId.value;
  const body = { name, base_url: baseUrl, models };
  // Key is write-only: only send it when the user actually typed one.
  if (apiKey) body.api_key = apiKey;
  el.llmCustomSubmit.disabled = true;
  requestLlmCustom(providerId ? "PUT" : "POST",
    providerId ? `/api/llm/providers/${encodeURIComponent(providerId)}` : "/api/llm/providers",
    body).finally(() => { el.llmCustomSubmit.disabled = false; });
}

el.llmCustomForm.addEventListener("submit", submitLlmCustom);
el.llmCustomCancel.addEventListener("click", resetLlmCustomForm);

registerView("settings", renderLlmSettings);
