/* graph2note — version comparison core (issue S3): pure builders, no DOM/IO.

   Consumes the read-only compare payload served by
   ``GET /api/documents/{id}/diff`` (which itself is S1's ``DiffReport`` plus
   per-block Markdown).  Everything here is string/object assembly so the Node
   behaviour harness can assert the exact markup contract offline.

   Zero model calls: the natural-language summary arrives pre-templated from the
   backend (``summary_lines``) — this module only lays it out.
*/
"use strict";

export const BLOCK_TYPE_LABELS = {
  heading: "标题",
  paragraph: "段落",
  list: "列表",
  formula: "公式",
  table: "表格",
  code: "代码",
  quote: "引用",
  image: "图片",
  diagram: "图表",
  flow: "流程图",
};

export const OP_LABELS = {
  added: "新增",
  removed: "删除",
  modified: "修改",
  moved: "移动",
  unchanged: "未变",
};

export const VERDICT_LABELS = {
  unchanged: "无改动",
  minor: "小幅改动",
  major: "较大改动",
};

export function blockTypeLabel(type) {
  return BLOCK_TYPE_LABELS[type] || type || "块";
}

export function opLabel(op) {
  return OP_LABELS[op] || op || "";
}

export function verdictLabel(verdict) {
  return VERDICT_LABELS[verdict] || verdict || "";
}

/* CSS class carrying the block-level highlight (added/removed/modified/moved). */
export function changeHighlight(op) {
  return `diff-${op || "unchanged"}`;
}

/* Compact diff badge for the version switcher, e.g. "+3 −1 ~2" (⇄ for moved).
   Returns "" for the first version (no previous to diff against). */
export function diffBadge(diff) {
  if (!diff || !diff.by_op) return "";
  const byOp = diff.by_op;
  const parts = [];
  if (byOp.added) parts.push(`+${byOp.added}`);
  if (byOp.removed) parts.push(`−${byOp.removed}`);
  if (byOp.modified) parts.push(`~${byOp.modified}`);
  if (byOp.moved) parts.push(`⇄${byOp.moved}`);
  return parts.join(" ");
}

export function verdictBadge(diff) {
  return diff && diff.verdict ? verdictLabel(diff.verdict) : "";
}

function indexBlocks(version) {
  const map = new Map();
  for (const block of (version && version.blocks) || []) {
    map.set(block.index, block);
  }
  return map;
}

/* Row-aligned change list: one row per S1 BlockChange, carrying the A-side and
   B-side block (either may be null for added/removed).  Row order is exactly
   S1's deterministic ``changes`` order, so the two columns stay aligned. */
export function buildRows(payload) {
  const aBlocks = indexBlocks(payload && payload.a);
  const bBlocks = indexBlocks(payload && payload.b);
  const changes = (payload && payload.report && payload.report.changes) || [];
  return changes.map((change) => {
    const aIndex = change.block_ref_a ? change.block_ref_a.index : null;
    const bIndex = change.block_ref_b ? change.block_ref_b.index : null;
    return {
      op: change.op,
      blockType: change.block_type,
      typeLabel: blockTypeLabel(change.block_type),
      similarity: change.similarity,
      aIndex,
      bIndex,
      a: aIndex == null ? null : aBlocks.get(aIndex) || null,
      b: bIndex == null ? null : bBlocks.get(bIndex) || null,
    };
  });
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* Per-block Markdown rendering.  ``renderMarkdown`` is injected (marked in the
   browser); the fallback keeps the raw snippet so the Node harness — which has
   no marked — can still assert block ownership. */
export function blockBodyHtml(block, renderMarkdown) {
  const source = block ? block.markdown || block.preview || "" : "";
  if (typeof renderMarkdown === "function") {
    try {
      return renderMarkdown(source);
    } catch (_) { /* fall through to plain text */ }
  }
  return `<p>${escapeHtml(source)}</p>`;
}

/* One side of one row: the block wrapper carries S1's deterministic anchor
   (``block-{index}``) and its ``data-block-index`` so a change can locate the
   matching block in the current-version column. */
export function blockCellHtml(row, block, side, options = {}) {
  const highlight = changeHighlight(row.op);
  if (!block) {
    return `<div class="diff-cell diff-empty-cell diff-side-${side}" data-side="${side}" aria-hidden="true"></div>`;
  }
  const latest = options.latest ? " diff-latest" : "";
  const locate = row.bIndex != null ? row.bIndex : row.aIndex;
  const tag = `${opLabel(row.op)} · ${row.typeLabel}`
    + (row.similarity != null ? ` · ${Math.round(row.similarity * 100)}%` : "");
  return `<div class="diff-cell diff-block ${highlight}${latest} diff-side-${side}"`
    + ` id="${side}-${block.anchor}"`
    + ` data-block-index="${block.index}" data-anchor="${block.anchor}"`
    + ` data-locate="${locate}"`
    + ` data-block-type="${escapeHtml(block.type)}" data-side="${side}"`
    + ` data-diff-block="${block.index}" role="button" tabindex="0"`
    + ` title="点击定位到当前版本的对应块">`
    + `<span class="diff-block-tag">${escapeHtml(tag)}</span>`
    + `<div class="diff-block-body">${blockBodyHtml(block, options.renderMarkdown)}</div>`
    + `</div>`;
}

/* Aligned side-by-side rows.  ``latestSide`` marks the column that belongs to
   the current (editable) version so locate/jump targets it. */
export function renderRowsHtml(payload, options = {}) {
  const rows = buildRows(payload);
  const latestSide = options.latestSide || "b";
  return rows.map((row) => {
    const aCell = blockCellHtml(row, row.a, "a", { ...options, latest: latestSide === "a" });
    const bCell = blockCellHtml(row, row.b, "b", { ...options, latest: latestSide === "b" });
    const focus = row.bIndex != null ? row.bIndex : row.aIndex;
    return `<div class="diff-row ${changeHighlight(row.op)}" data-diff-row="${focus}" data-op="${row.op}">`
      + aCell + bCell + `</div>`;
  }).join("");
}

/* Version header contents for one compare column: time / source / model /
   read-only marker and the per-version original image (U3 large-image viewer
   source).  The column container carries ``diff-col-head diff-side-*``. */
export function renderVersionHeadHtml(version, side, options = {}) {
  if (!version) return `<div class="diff-col-head-line dim">未选择版本</div>`;
  const history = version.is_history && !version.is_edit
    ? `<span class="version-badge history-badge">历史版本</span>` : "";
  const edit = version.is_edit ? `<span class="version-badge edit-badge">当前编辑</span>` : "";
  const current = version.is_current && !version.is_edit
    ? `<span class="version-badge current-badge">当前版本</span>` : "";
  const image = options.imageUrl
    ? `<img class="diff-version-img" src="${escapeHtml(options.imageUrl)}"`
      + ` alt="该版本预处理原图" data-viewer-src="${escapeHtml(options.imageUrl)}" />`
    : `<span class="diff-no-image dim">该版本无原图</span>`;
  return `<div class="diff-col-head-line"><span class="diff-col-side">${side.toUpperCase()}</span>`
    + `<span class="diff-version-id">${escapeHtml(version.version_id)}</span>`
    + `${current}${history}${edit}</div>`
    + `<div class="diff-col-meta dim">${escapeHtml(version.created_at || "时间未记录")}`
    + ` · ${escapeHtml(version.source_label || version.source || "")}`
    + `${version.model ? " · " + escapeHtml(version.model) : ""}</div>`
    + `<div class="diff-col-image">${image}</div>`;
}

/* Summary bar: the backend-templated sentences (zero model) + exact op counts
   taken from the same S1 DiffSummary the numbers came from. */
export function renderSummaryBar(payload) {
  const report = payload && payload.report;
  if (!report) {
    return `<div class="diff-summary-line dim">${escapeHtml((payload && payload.summary_lines || [])[0] || "无可对比数据。")}</div>`;
  }
  const summary = report.summary || {};
  const lines = payload.summary_lines || [];
  const chips = ["added", "removed", "modified", "moved"]
    .filter((op) => summary.by_op && summary.by_op[op])
    .map((op) => `<span class="diff-chip ${changeHighlight(op)}">${opLabel(op)} ${summary.by_op[op]}</span>`)
    .join("");
  const verdict = `<span class="diff-verdict ${changeHighlight(summary.verdict)}">${escapeHtml(verdictLabel(summary.verdict))}</span>`;
  return `<div class="diff-summary-head">${verdict}${chips}`
    + `<span class="diff-density dim">变更 ${summary.changed_blocks || 0}/${summary.total_blocks || 0} 块 · 密度 ${(summary.change_density || 0).toFixed(2)}</span></div>`
    + `<div class="diff-summary-lines">${lines.map((line) => `<span class="diff-summary-line">${escapeHtml(line)}</span>`).join("")}</div>`;
}

/* Read-only notice shown whenever a historical version is on screen (AC1:
   obvious "历史版本" marker + guidance back to the editable latest). */
export function renderReadOnlyNotice(payload) {
  const versions = [payload && payload.a, payload && payload.b].filter(Boolean);
  const historical = versions.filter((version) => version.is_history && !version.is_edit);
  if (!historical.length) return "";
  const latest = (payload && payload.b && !payload.b.is_history) ? payload.b
    : (payload && payload.a && !payload.a.is_history) ? payload.a : null;
  const names = historical.map((version) => version.version_id).join("、");
  const guidance = latest
    ? `只读查看历史版本 ${names}；编辑始终作用于最新版（${latest.version_id}）。`
    : `只读查看历史版本 ${names}。`;
  return `<span class="diff-readonly-text">🔒 ${escapeHtml(guidance)}</span>`;
}

/* Version switcher list (newest first, matching the U3 index): time, source and
   the S2 diff badge.  Items are buttons so a click selects the version. */
export function renderVersionListHtml(chain, options = {}) {
  const versions = (chain && chain.versions) || [];
  const selected = options.selectedVersionId || null;
  const latestId = options.latestVersionId || (chain && chain.latest_version_id) || null;
  if (!versions.length) return `<span class="dim">暂无版本记录</span>`;
  return versions.slice().reverse().map((version) => {
    const isCurrent = (latestId && version.version_id === latestId) || (!latestId && version.current);
    const badge = isCurrent ? "当前" : (version.is_edit ? "编辑" : "历史");
    const diff = version.diff || null;
    const diffBadgeText = diffBadge(diff);
    const diffHtml = diffBadgeText
      ? `<span class="version-diff-badge ${changeHighlight(diff.verdict)}" title="${escapeHtml(verdictLabel(diff.verdict))}">${escapeHtml(diffBadgeText)}</span>`
      : (version.index === 0 ? `<span class="version-diff-badge dim">首版</span>` : "");
    const classes = ["version-item"];
    if (isCurrent) classes.push("current");
    if (version.is_history && !version.is_edit) classes.push("history");
    if (selected && selected === version.version_id) classes.push("selected");
    return `<button type="button" class="${classes.join(" ")}" data-version-id="${escapeHtml(version.version_id)}"`
      + ` data-version-index="${version.index}"`
      + (isCurrent ? ` data-current="1"` : "")
      + (version.is_edit ? ` data-edit="1"` : "")
      + `>`
      + `<span class="version-badge">${badge}</span>`
      + `<span class="version-time dim">${escapeHtml(version.created_at || "未记录")}</span>`
      + `<span class="version-source">${escapeHtml(version.source_label || version.source || "")}</span>`
      + diffHtml
      + `</button>`;
  }).join("");
}
