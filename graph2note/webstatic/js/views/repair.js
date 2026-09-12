/* graph2note — 黑图修复报告路由（R1 在 U1 三区骨架下的挂载点）。

   R1 把「黑图修复报告」交付为自持的经典脚本 `/static/repair.js`（自带导航入口、
   zone、样式与轮询），index.html 仍以 `<script src="/static/repair.js">` 引入
   （在 type="module" 入口之前执行）。U1 之后路由是 URL 的唯一事实来源，所以这里
   把 repair 视图注册进 hash 路由，并委托给该脚本暴露的 mount()：

     parseHash("#repair") -> { name: "repair" } -> 本视图 -> window.__g2nRepair.mount()

   repair.js 不再自行监听 hashchange；隐藏/显示由 router.hideAll() 与本模块负责。
*/
"use strict";

import { registerView } from "../router.js";

registerView("repair", () => {
  if (window.__g2nRepair && typeof window.__g2nRepair.mount === "function") {
    window.__g2nRepair.mount();
  }
});
