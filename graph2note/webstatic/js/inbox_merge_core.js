/* graph2note — continuity merge queue helpers (issue 03).
   Pure functions only: no DOM, no network, no imports, so the Inbox merge
   block can be exercised offline (tests/inbox_merge_dom.mjs).  The view
   (`views/inbox.js`) owns the fetch + event wiring. */
"use strict";

export const MERGE_REASON_LABEL = "可合并";

export const MERGE_TIER_LABELS = {
  significant: "显著",
  suggested: "疑似",
};

const TIER_ORDER = ["significant", "suggested"];

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Human evidence line: "同 PDF 第 m–n 页" / "尾首重叠 N 块". */
export function mergeEvidenceLabel(candidate) {
  if (!candidate) return "";
  const explicit = String(candidate.evidence_label || "").trim();
  if (explicit) return explicit;
  const evidence = candidate.evidence || {};
  if (evidence.kind === "page_adjacency") {
    const a = evidence.page_a;
    const b = evidence.page_b;
    if (a != null && b != null) {
      const low = Math.min(a, b);
      const high = Math.max(a, b);
      return `同 PDF 第 ${low}–${high} 页`;
    }
    return "同 PDF 页序相邻";
  }
  return `尾首重叠 ${Number(evidence.overlap_blocks || candidate.overlap_blocks || 0)} 块`;
}

/** "显著" / "疑似" badge text. */
export function mergeTierLabel(candidate) {
  const tier = candidate && candidate.tier;
  return MERGE_TIER_LABELS[tier] || "可合并";
}

/** "「标题 A」/「标题 B」" with a graceful fallback to document ids. */
export function mergePairTitles(candidate) {
  if (!candidate) return "";
  const titles = Array.isArray(candidate.titles) ? candidate.titles : [];
  const first = String(titles[0] || candidate.document_id || "");
  const second = String(titles[1] || candidate.target_id || "");
  return `${first} / ${second}`;
}

/** Flatten the `/api/continuity/candidates` payload into one ordered list. */
export function pendingMergeCandidates(payload) {
  const out = [];
  const source = payload || {};
  for (const tier of TIER_ORDER) {
    const items = Array.isArray(source[tier]) ? source[tier] : [];
    for (const item of items) {
      if (item && item.document_id && item.target_id) out.push(item);
    }
  }
  return out;
}

/** Look up a candidate by its canonical pair key. */
export function candidateByKey(candidates, key) {
  return (candidates || []).find((item) => item && item.key === key) || null;
}

/** One queue row: evidence + both titles + confirm/reject actions. */
export function mergeCandidateHtml(candidate) {
  if (!candidate) return "";
  const key = escapeHtml(candidate.key || `${candidate.document_id}|${candidate.target_id}`);
  const tier = escapeHtml(mergeTierLabel(candidate));
  const muted = candidate.tier === "suggested" ? " inbox-merge-muted" : "";
  const evidence = escapeHtml(mergeEvidenceLabel(candidate));
  const titles = escapeHtml(mergePairTitles(candidate));
  const phash = candidate.phash_distance == null
    ? "" : `<span class="inbox-merge-distance">pHash 距离 ${escapeHtml(candidate.phash_distance)}</span>`;
  const previews = (candidate.evidence && Array.isArray(candidate.evidence.previews)
    ? candidate.evidence.previews : [])
    .slice(0, 3)
    .map((text) => `<li>${escapeHtml(text)}</li>`)
    .join("");
  const previewList = previews ? `<ul class="inbox-merge-previews">${previews}</ul>` : "";
  return `<article class="inbox-merge-item${muted}" data-merge-key="${key}">
    <div class="inbox-merge-main">
      <span class="inbox-merge-tier">${tier}</span>
      <span class="inbox-merge-title">${titles}</span>
      <span class="inbox-merge-evidence">${evidence}</span>
      ${phash}
      ${previewList}
    </div>
    <div class="inbox-merge-actions">
      <button type="button" class="inbox-merge-confirm" data-merge-confirm="${key}">确认合并</button>
      <button type="button" class="inbox-merge-reject" data-merge-reject="${key}">拒绝</button>
    </div>
  </article>`;
}

/** The whole queue (ordered, significant first). */
export function mergeListHtml(candidates) {
  const list = Array.isArray(candidates) ? candidates : [];
  return list.map(mergeCandidateHtml).join("");
}

/** Safe empty state for the merge block. */
export function mergeEmptyHtml(message) {
  const text = message || "没有可合并的连续笔记。";
  return `<div class="inbox-merge-empty dim">${escapeHtml(text)}</div>`;
}

/** Post-merge confirmation pointing at the new document's version chain. */
export function mergeResultHtml(report) {
  if (!report || !report.merged_document_id) return "";
  const id = encodeURIComponent(report.merged_document_id);
  const title = escapeHtml(report.title || report.merged_document_id);
  const overlap = Number(report.overlap_blocks || 0);
  return `<p class="inbox-merge-result-line">已合并为
    <a href="#doc/${id}/versions" data-route="#doc/${id}/versions">${title}</a>
    （重叠 ${overlap} 块；版本链首版来源：合并）</p>`;
}
