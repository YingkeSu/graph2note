/* graph2note — shared constants and small pure helpers (U1 module split).

   No DOM state, no imports: safe for every other module to depend on. */
"use strict";

export const POLL_MS = 1200;
export const SAVE_MS = 800;

export const $ = (selector) => document.querySelector(selector);

export function esc(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

export function escapeRe(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function displayTime(value) {
  return value ? String(value).replace("T", " ") : "未记录";
}
