/* graph2note — tag vocabulary view (moved out of Library by U1; same
   governance behaviour: rename / merge / create). */
"use strict";

import { el } from "../state.js";
import { api } from "../api.js";
import { esc } from "../utils.js";
import { registerView } from "../router.js";
import { showToast } from "../ui.js";

export async function renderTagVocabulary() {
  if (!el.tagList) return;
  let tags = [];
  try { tags = await api("/api/tags"); }
  catch (e) { showToast("加载标签词表失败：" + e.message, "err"); return; }
  el.tagList.innerHTML = tags.length ? tags.map((item) => `
    <span class="tag-vocabulary-item">
      <span class="tag-name">#${esc(item.tag)}</span>
      <span class="dim">${item.count} 份${item.aliases && item.aliases.length ? ` · 别名：${esc(item.aliases.join("、"))}` : ""}</span>
      <button class="tag-action" data-tag-action="rename" data-tag="${esc(item.tag)}">重命名</button>
      <button class="tag-action" data-tag-action="merge" data-tag="${esc(item.tag)}">合并</button>
    </span>`).join("") : `<span class="dim">暂无标签，打开文档后可添加。</span>`;
  el.tagList.querySelectorAll("button[data-tag-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const source = button.dataset.tag;
      const target = window.prompt(button.dataset.tagAction === "merge" ? "合并到哪个标签？" : "重命名为？", source);
      if (!target || target === source) return;
      try {
        await api(`/api/tags/${button.dataset.tagAction}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source, target }),
        });
        await renderTagVocabulary();
        showToast(button.dataset.tagAction === "merge" ? "标签已合并" : "标签已重命名", "ok");
      } catch (e) { showToast("标签治理失败：" + e.message, "err"); }
    });
  });
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
    await api("/api/tags", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: value }),
    });
    el.tagCreateInput.value = "";
    await renderTagVocabulary();
  } catch (e) { showToast("新增标签失败：" + e.message, "err"); }
});

registerView("tags", renderTags);
