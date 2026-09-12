/* graph2note — ES-module entry (U1).

   Zero-build: the browser loads this as `<script type="module">`; each view is a
   sibling module under /static/js/.  Views self-register with the hash router on
   import, so the order below is only about wiring the shell before the first
   render.

   Module map:
     js/utils.js         pure helpers + constants
     js/api.js           fetch wrapper
     js/state.js         shared state + element registry + zone visibility
     js/router.js        hash parsing, view registry, go/render
     js/ui.js            shell: toast, nav highlight, sidebar, collection tree
     js/jobs.js          parse-job working state + polling
     js/views/*.js       one module per view (repair.js = R1 bridge)
*/
"use strict";

import "./js/views/library.js";
import "./js/views/tags.js";
import "./js/views/pdf.js";
import "./js/views/inbox.js";
import "./js/views/settings.js";
import "./js/views/timeline.js";
import "./js/views/graph.js";
import "./js/views/dashboard.js";
import "./js/views/vault.js";
import "./js/views/upload.js";
import "./js/views/document.js";
import "./js/views/repair.js";   // R1 黑图修复报告（zone 由 /static/repair.js 自持）

import { render, startRouter } from "./js/router.js";
import { wireShell } from "./js/ui.js";
import { flushAutosave } from "./js/views/document.js";

wireShell();
startRouter();
render();

window.addEventListener("beforeunload", flushAutosave);
