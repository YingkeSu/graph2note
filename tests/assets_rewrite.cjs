// Node unit test for the asset path rewriter (issue 06b + 06c).
// Pure function under graph2note/webstatic/assets.js — no DOM / no build.
// Run: node tests/assets_rewrite.cjs
"use strict";
const assert = require("node:assert");
const {
  resolveAssetSrc,
  isAssetRef,
  normalizeImageArgs,
} = require("../graph2note/webstatic/assets.js");

// 1) job view relative asset ref -> /api/jobs/<id>/assets/<name>
assert.strictEqual(
  resolveAssetSrc("assets/arch.png", "job", "job-abc123"),
  "/api/jobs/job-abc123/assets/arch.png",
  "job view rewrite"
);

// 2) doc view relative asset ref -> /api/documents/<id>/assets/<name>
assert.strictEqual(
  resolveAssetSrc("assets/flow.png", "doc", "doc-xyz789"),
  "/api/documents/doc-xyz789/assets/flow.png",
  "doc view rewrite"
);

// 3) external URL / absolute path left untouched
assert.strictEqual(
  resolveAssetSrc("https://example.com/x.png", "doc", "doc-1"),
  "https://example.com/x.png",
  "external URL untouched"
);
assert.strictEqual(
  resolveAssetSrc("/api/other/y.png", "job", "job-1"),
  "/api/other/y.png",
  "absolute path untouched"
);

// 4) only "assets/"-prefixed relative refs are rewritten
assert.strictEqual(isAssetRef("assets/a.png"), true);
assert.strictEqual(isAssetRef("images/a.png"), false);
assert.strictEqual(isAssetRef("Assets/a.png"), false); // case-sensitive prefix
assert.strictEqual(isAssetRef(null), false);
assert.strictEqual(isAssetRef(undefined), false);

// 5) asset name (with possible slash-ish path) is preserved through encode
assert.strictEqual(
  resolveAssetSrc("assets/sub/rebuild.png", "doc", "doc 1"),
  "/api/documents/doc%201/assets/sub%2Frebuild.png",
  "sub-path name preserved"
);

// ---- issue 06c: marked signature compat -------------------------------------

// 6) marked v4 legacy string signature (href, title, text)
assert.deepStrictEqual(
  normalizeImageArgs("assets/arch.png", "fig 1", "rebuild"),
  { href: "assets/arch.png", title: "fig 1", text: "rebuild" },
  "legacy string signature"
);
assert.deepStrictEqual(
  normalizeImageArgs("assets/a.png", null, "alt"),
  { href: "assets/a.png", title: null, text: "alt" },
  "legacy null title"
);

// 7) marked v12+ token object signature — the regression that broke preview
const token = { type: "image", raw: "![r](assets/arch.png)", href: "assets/arch.png",
                title: null, text: "rebuild", tokens: [] };
assert.deepStrictEqual(
  normalizeImageArgs(token),
  { href: "assets/arch.png", title: null, text: "rebuild" },
  "token object signature"
);
// end-to-end through the rewriter: token href -> context API URL
assert.strictEqual(
  resolveAssetSrc(normalizeImageArgs(token).href, "doc", "doc-42"),
  "/api/documents/doc-42/assets/arch.png",
  "token href rewritten end-to-end"
);
// token object whose href is NOT an asset ref stays untouched after normalize
assert.strictEqual(
  resolveAssetSrc(normalizeImageArgs({ href: "https://x/y.png" }).href, "doc", "doc-42"),
  "https://x/y.png",
  "token external href untouched"
);

// 8) defensive: token object never passes isAssetRef, malformed args safe
assert.strictEqual(isAssetRef(token), false, "token object is not an asset ref");
assert.deepStrictEqual(
  normalizeImageArgs(undefined, undefined, undefined),
  { href: "", title: null, text: "" },
  "malformed args normalize safely"
);
assert.strictEqual(
  resolveAssetSrc(normalizeImageArgs({ href: 123 }).href, "job", "j"),
  "",
  "non-string token href normalizes to empty"
);

console.log("assets_rewrite: all assertions passed ✓");