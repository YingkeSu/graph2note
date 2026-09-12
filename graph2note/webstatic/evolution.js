/* graph2note — S2 evolution anchoring panel (self-contained, minimal).
 *
 * Kept out of app.js on purpose: it reads the existing `#doc/<id>` hash route,
 * its own `<section id="evolution-panel">` mount point in index.html, and only
 * talks to the S2 API.  The global layout work (U1) can move app.js without
 * touching this file.
 *
 * Two read-first blocks:
 *   - 演进时间线: GET /api/documents/<id>/versions  (source + diff summary)
 *   - 相似手稿建议: GET /api/documents/<id>/candidates (read-only suggestions)
 * Suggestions are never auto-linked; 确认 posts a manual relation, 忽略
 * remembers the rejection so the pair is not suggested again.
 */
"use strict";

(function () {
  const panel = document.getElementById("evolution-panel");
  if (!panel) return;

  const body = document.getElementById("evolution-body");
  const title = document.getElementById("evolution-title");
  const status = document.getElementById("evolution-status");
  let currentId = null;

  function esc(value) {
    const d = document.createElement("div");
    d.textContent = value == null ? "" : String(value);
    return d.innerHTML;
  }

  function currentDocumentId() {
    const match = String(location.hash || "").replace(/^#/, "").match(/^doc\/(.+)$/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  async function api(route, opts) {
    const res = await fetch(route, opts || {});
    if (!res.ok) throw new Error(route + " -> HTTP " + res.status);
    return res.json();
  }

  function renderChain(chain) {
    if (!chain || !chain.count) {
      return '<div class="dim">暂无版本记录。</div>';
    }
    const rows = chain.versions.map(function (entry) {
      let diff = "首个版本（无前版可比）";
      if (entry.diff) {
        diff = entry.diff.verdict + " · 变更 " + entry.diff.changed_blocks +
          "/" + entry.diff.total_blocks + " · 密度 " + entry.diff.change_density;
      }
      const time = entry.created_at || "-";
      return '<div class="evolution-row" style="padding:4px 0;border-bottom:1px dashed #ddd">' +
        '<div><strong>' + esc(entry.source_label) + '</strong> ' +
        '<span class="dim">' + esc(time) + '</span>' +
        (entry.current ? ' <span class="dim">（当前）</span>' : '') +
        (entry.is_edit ? ' <span class="dim">（未提交编辑）</span>' : '') + '</div>' +
        '<div class="dim">' + esc(entry.version_id) + ' · ' + esc(diff) + '</div>' +
        '</div>';
    }).join("");
    return '<div class="dim" style="margin-bottom:4px">共 ' + chain.count +
      ' 个版本' + (chain.has_uncommitted_edit ? '（含未提交编辑）' : '') + '</div>' + rows;
  }

  function renderCandidates(view) {
    if (!view || view.empty) {
      return '<div class="dim">未检测到相似手稿。</div>';
    }
    const threshold = view.max_distance;
    return '<div class="dim" style="margin-bottom:4px">阈值：汉明距离 ≤ ' + threshold +
      '（共 64 位）</div>' +
      view.candidates.map(function (candidate) {
        return '<div class="evolution-row" style="padding:4px 0;border-bottom:1px dashed #ddd">' +
          '<div>检测到相似手稿：' + esc(candidate.title || candidate.document_id) +
          ' <span class="dim">' + esc(candidate.document_id) + '</span></div>' +
          '<div class="dim">相似度 ' + candidate.similarity + '（距离 ' + candidate.distance + '）</div>' +
          '<div style="margin-top:2px">' +
          '<button class="btn small" data-confirm="' + esc(candidate.document_id) +
          '" data-distance="' + candidate.distance + '">确认关联</button> ' +
          '<button class="btn small" data-reject="' + esc(candidate.document_id) +
          '" data-distance="' + candidate.distance + '">忽略</button>' +
          '</div></div>';
      }).join("");
  }

  async function refresh() {
    const id = currentDocumentId();
    currentId = id;
    if (!id) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    if (title) title.textContent = id;
    status.textContent = "加载中…";
    try {
      const [chain, candidates] = await Promise.all([
        api("/api/documents/" + encodeURIComponent(id) + "/versions"),
        api("/api/documents/" + encodeURIComponent(id) + "/candidates"),
      ]);
      if (id !== currentId) return;
      body.innerHTML =
        '<h4 style="margin:6px 0 2px">演进时间线</h4>' + renderChain(chain) +
        '<h4 style="margin:10px 0 2px">相似手稿建议（只建议，确认后关联）</h4>' +
        renderCandidates(candidates);
      status.textContent = "";
    } catch (err) {
      body.innerHTML = "";
      status.textContent = "加载失败：" + err.message;
    }
  }

  async function act(id, route, candidateId, distance) {
    try {
      await api("/api/documents/" + encodeURIComponent(id) + route, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_id: candidateId, distance: distance }),
      });
      await refresh();
    } catch (err) {
      status.textContent = "操作失败：" + err.message;
    }
  }

  panel.addEventListener("click", function (event) {
    const button = event.target.closest("button[data-confirm], button[data-reject]");
    if (!button || !currentId) return;
    const distance = Number(button.getAttribute("data-distance"));
    if (button.hasAttribute("data-confirm")) {
      act(currentId, "/relations", button.getAttribute("data-confirm"), distance);
    } else {
      act(currentId, "/candidates/reject", button.getAttribute("data-reject"), distance);
    }
  });

  window.addEventListener("hashchange", refresh);
  refresh();
})();
