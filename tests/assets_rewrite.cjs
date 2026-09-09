// Node unit test for the asset path rewriter (issue 06b).
// Pure function under graph2note/webstatic/assets.js — no DOM / no build.
// Run: node tests/assets_rewrite.cjs
"use strict";
const assert = require("node:assert");
const { resolveAssetSrc, isAssetRef } = require("../graph2note/webstatic/assets.js");

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

console.log("assets_rewrite: all assertions passed ✓");