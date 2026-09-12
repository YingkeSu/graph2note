/* graph2note — thin JSON/blob fetch wrapper around the local API (U1 split). */
"use strict";

export async function api(route, opts = {}) {
  const res = await fetch(route, opts);
  const ct = res.headers.get("content-type") || "";
  let body;
  try {
    body = ct.includes("json") ? await res.json() : await res.blob();
  } catch (_) {
    body = {};
  }
  if (!res.ok) {
    const msg = (body && body.detail) || res.statusText;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return body;
}
