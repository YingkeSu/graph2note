// Node unit test for the structure-diagram presentation helpers (SPW D3).
// Pure string builders in graph2note/webstatic/assets.js — no DOM / no build.
// Run: node tests/diagram_presentation.cjs
"use strict";
const assert = require("node:assert");
const {
  isDiagramAssetRef,
  buildDiagramFigure,
  resolveAssetSrc,
} = require("../graph2note/webstatic/assets.js");

// 1) only rendered diagram/flow assets are recognised
assert.strictEqual(isDiagramAssetRef("assets/doc-diagram-0.png"), true);
assert.strictEqual(isDiagramAssetRef("assets/doc-flow-12.png"), true);
assert.strictEqual(isDiagramAssetRef("assets/sub/doc-diagram-3.png"), true);
assert.strictEqual(isDiagramAssetRef("assets/photo.png"), false);
assert.strictEqual(isDiagramAssetRef("assets/doc-thumb-0.png"), false);
assert.strictEqual(isDiagramAssetRef("assets/doc-diagram.png"), false);
assert.strictEqual(isDiagramAssetRef("https://x/y-diagram-1.png"), true);
assert.strictEqual(isDiagramAssetRef(null), false);
assert.strictEqual(isDiagramAssetRef({ href: "assets/a-diagram-0.png" }), false);

// 2) a diagram becomes a labelled figure with zoom affordance
const html = buildDiagramFigure("/api/documents/d1/assets/doc-diagram-0.png", "主流程", null);
assert.ok(html.startsWith('<figure class="g2n-diagram">'), html);
assert.ok(html.includes('src="/api/documents/d1/assets/doc-diagram-0.png"'));
assert.ok(html.includes('alt="主流程"'));
assert.ok(html.includes('<figcaption class="g2n-diagram-caption">主流程</figcaption>'));
assert.ok(html.includes('tabindex="0"'));
assert.ok(html.includes('role="button"'));
assert.ok(html.endsWith("</figure>"));

// 3) no caption -> no empty figcaption, alt still present and empty
const bare = buildDiagramFigure("assets/d-diagram-1.png", "", null);
assert.ok(!bare.includes("<figcaption"));
assert.ok(bare.includes('alt=""'));

// 4) title becomes a title attribute; hostile text is escaped everywhere
const hostile = buildDiagramFigure(
  'assets/x-diagram-0.png" onerror="alert(1)',
  '<b>标题</b>',
  'a"b<c'
);
assert.ok(!hostile.includes("onerror=\"alert(1)\""), "src escaped");
assert.ok(!hostile.includes("<b>标题</b>"), "caption escaped");
assert.ok(hostile.includes("&lt;b&gt;标题&lt;/b&gt;"));
assert.ok(hostile.includes("title=\"a&quot;b&lt;c\""));

// 5) an ordinary image ref is not turned into a figure (document.js keeps the
//    plain <img> branch) — isDiagramAssetRef is the single switch.
assert.strictEqual(isDiagramAssetRef("assets/scan.png"), false);
assert.strictEqual(
  resolveAssetSrc("assets/doc-diagram-0.png", "doc", "d1"),
  "/api/documents/d1/assets/doc-diagram-0.png"
);

console.log("diagram_presentation: all assertions passed ✓");
