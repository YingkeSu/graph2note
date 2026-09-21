/* Workspace chrome owns open-view navigation and panel visibility.
   Views still own their content; the hash router remains navigation authority. */
import { go } from "./router.js";
import { api } from "./api.js";

const titles = {
  library: "文档库", graph: "知识图谱", timeline: "时间轴", dashboard: "数据看板",
  inbox: "待整理", tags: "标签", ask: "问答", settings: "设置", reports: "科研周报",
  "vault-export": "导出 Vault", upload: "新解析", repair: "修复报告",
};
const tabs = [];
let current = null;
let host;

function renderTabs(focusKey = null) {
  host.replaceChildren();
  for (const tab of tabs) {
    const item = document.createElement("div");
    item.className = "workspace-tab";
    item.classList.toggle("active", tab.key === current);
    const open = document.createElement("button");
    open.type = "button";
    open.className = "workspace-tab-open";
    open.textContent = tab.title;
    open.title = tab.title;
    open.setAttribute("role", "tab");
    open.setAttribute("aria-selected", String(tab.key === current));
    open.setAttribute("aria-controls", "content");
    open.tabIndex = tab.key === current ? 0 : -1;
    open.addEventListener("click", () => go(tab.hash));
    open.addEventListener("keydown", event => {
      const index = tabs.indexOf(tab);
      let target;
      if (event.key === "ArrowRight") target = tabs[(index + 1) % tabs.length];
      if (event.key === "ArrowLeft") target = tabs[(index + tabs.length - 1) % tabs.length];
      if (event.key === "Home") target = tabs[0];
      if (event.key === "End") target = tabs.at(-1);
      if (target) {
        event.preventDefault();
        // Focus moves synchronously; hashchange updates selection afterwards.
        host.querySelectorAll('[role="tab"]')[tabs.indexOf(target)].focus();
        go(target.hash);
      }
      if (event.key === "Delete") { event.preventDefault(); closeTab(tab); }
    });
    const close = document.createElement("button");
    close.type = "button";
    close.className = "workspace-tab-close";
    close.textContent = "×";
    close.setAttribute("aria-label", `关闭 ${tab.title}`);
    close.addEventListener("click", () => closeTab(tab));
    item.append(open, close);
    host.append(item);
    if (focusKey === tab.key) open.focus({ preventScroll: true });
  }
  host.querySelector('.workspace-tab.active')?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function closeTab(tab) {
  const index = tabs.indexOf(tab);
  const wasCurrent = tab.key === current;
  tabs.splice(index, 1);
  if (wasCurrent) {
    const next = tabs[Math.min(index, tabs.length - 1)];
    go(next?.hash || "#library");
  } else renderTabs(current);
}

export function syncWorkspace(route) {
  if (!host) return;
  const focusWithin = host.contains(document.activeElement);
  current = route.id ? `${route.name}/${route.id}` : route.name;
  let tab = tabs.find(item => item.key === current);
  if (!tab) {
    tab = { key: current, title: titles[route.name] || (route.name === "paper" ? "论文" : "文档") };
    tabs.push(tab);
    if (route.id) {
      const saved = tab;
      api(`/api/documents/${encodeURIComponent(route.id)}`).then(doc => {
        if (!tabs.includes(saved)) return;
        saved.title = doc.title || saved.title;
        renderTabs(host.contains(document.activeElement) ? current : null);
      }).catch(() => { /* The content view owns its retryable error. */ });
    }
  }
  tab.hash = location.hash || "#library";
  renderTabs(focusWithin ? current : null);
}

export function wireWorkspace() {
  host = document.getElementById("workspace-tabs");
  const panel = document.getElementById("graph-filters");
  const toggle = document.getElementById("graph-filter-toggle");
  const zone = document.getElementById("graph-zone");
  let collapsed = window.matchMedia("(max-width: 900px)").matches;
  try {
    const saved = localStorage.getItem("graph2note.graph-filters-collapsed");
    if (saved !== null) collapsed = saved === "1";
  } catch (_) { /* private browsing */ }
  function apply() {
    zone.classList.toggle("filters-collapsed", collapsed);
    panel.hidden = collapsed;
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.textContent = collapsed ? "显示筛选" : "隐藏筛选";
  }
  toggle.addEventListener("click", () => {
    collapsed = !collapsed;
    apply();
    try { localStorage.setItem("graph2note.graph-filters-collapsed", collapsed ? "1" : "0"); } catch (_) {}
  });
  apply();
}
