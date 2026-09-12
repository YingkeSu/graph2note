// Offline contract test for the issue-03 Inbox continuity queue helpers.
//   node tests/inbox_merge_dom.mjs
//
// `inbox_merge_core.js` is a dependency-free ES module (no DOM, no fetch), so
// it can be imported and exercised in plain Node.  The view
// (`views/inbox.js`) owns the network/DOM wiring; this pins the evidence
// labels, safe escaping, action data-attributes and the post-merge hand-off.
import assert from "node:assert";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const modulePath = path.join(
  here, "..", "graph2note", "webstatic", "js", "inbox_merge_core.js",
);
const core = await import(pathToFileURL(modulePath).href);
const {
  MERGE_REASON_LABEL, MERGE_TIER_LABELS, mergeEvidenceLabel, mergeTierLabel,
  mergePairTitles, pendingMergeCandidates, candidateByKey, mergeCandidateHtml,
  mergeListHtml, mergeEmptyHtml, mergeResultHtml,
} = core;

// ---- 1) reason label + tier labels -----------------------------------------
assert.strictEqual(MERGE_REASON_LABEL, "可合并");
assert.deepStrictEqual(MERGE_TIER_LABELS, { significant: "显著", suggested: "疑似" });

// ---- 2) evidence labels for both tiers -------------------------------------
const significant = {
  tier: "significant", key: "a|b", document_id: "a", target_id: "b",
  titles: ["手稿A", "手稿B"], evidence_label: "同 PDF 第 3–4 页",
  evidence: { kind: "page_adjacency", page_a: 3, page_b: 4 },
  phash_distance: null, overlap_blocks: null,
};
const suggested = {
  tier: "suggested", key: "c|d", document_id: "c", target_id: "d",
  titles: ["C", "D"], evidence_label: "",
  evidence: { kind: "tail_head_overlap", overlap_blocks: 3, previews: ["甲", "乙"] },
  phash_distance: 5, overlap_blocks: 3,
};
assert.strictEqual(mergeEvidenceLabel(significant), "同 PDF 第 3–4 页");
assert.strictEqual(mergeEvidenceLabel(suggested), "尾首重叠 3 块");
assert.strictEqual(mergeEvidenceLabel({ tier: "significant", evidence: { kind: "page_adjacency", page_a: 9, page_b: 8 } }),
  "同 PDF 第 8–9 页");
assert.strictEqual(mergeTierLabel(significant), "显著");
assert.strictEqual(mergeTierLabel(suggested), "疑似");
assert.strictEqual(mergeTierLabel({}), "可合并");
assert.strictEqual(mergePairTitles(significant), "手稿A / 手稿B");
assert.strictEqual(mergePairTitles({ document_id: "x", target_id: "y" }), "x / y");

// ---- 3) payload flattening + lookup ----------------------------------------
const payload = { significant: [significant], suggested: [suggested], counts: {} };
assert.deepStrictEqual(pendingMergeCandidates(payload).map((c) => c.key), ["a|b", "c|d"]);
assert.deepStrictEqual(pendingMergeCandidates(null), []);
assert.strictEqual(candidateByKey([significant, suggested], "c|d"), suggested);
assert.strictEqual(candidateByKey([significant], "zz"), null);

// ---- 4) queue row markup + actions + escaping ------------------------------
const sigHtml = mergeCandidateHtml(significant);
assert.ok(sigHtml.includes('data-merge-key="a|b"'));
assert.ok(sigHtml.includes('data-merge-confirm="a|b"'));
assert.ok(sigHtml.includes('data-merge-reject="a|b"'));
assert.ok(sigHtml.includes("确认合并"));
assert.ok(sigHtml.includes("拒绝"));
assert.ok(sigHtml.includes("同 PDF 第 3–4 页"));
assert.ok(sigHtml.includes("显著"));
assert.ok(!sigHtml.includes("inbox-merge-muted"));

const susHtml = mergeCandidateHtml(suggested);
assert.ok(susHtml.includes("inbox-merge-muted"));
assert.ok(susHtml.includes("pHash 距离 5"));
assert.ok(susHtml.includes("尾首重叠 3 块"));
assert.ok(susHtml.includes("甲"));
assert.strictEqual((mergeListHtml([significant, suggested]).match(/<article/g) || []).length, 2);
assert.ok(mergeEmptyHtml().includes("没有可合并的连续笔记"));
assert.ok(mergeEmptyHtml("检测失败").includes("检测失败"));

// escaping: a hostile title never becomes markup
const hostile = mergeCandidateHtml({
  ...significant,
  titles: ["<img src=x onerror=alert(1)>", "b"],
});
assert.ok(!hostile.includes("<img"));
assert.ok(hostile.includes("&lt;img"));

// ---- 5) post-merge hand-off to the version switcher ------------------------
const result = mergeResultHtml({
  merged_document_id: "doc-9", title: "手稿A", overlap_blocks: 2,
});
assert.ok(result.includes("#doc/doc-9/versions"));
assert.ok(result.includes("重叠 2 块"));
assert.ok(result.includes("合并"));
assert.strictEqual(mergeResultHtml(null), "");

console.log("inbox merge dom: all assertions passed");
