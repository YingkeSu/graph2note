/* Assets path rewriting for the three-pane preview (issue 06b).

   When the backend renders a rebuilt diagram (architecture/flow image) it
   embeds relative refs like ``![rebuild](assets/xxx.png)`` into the Markdown.
   The browser resolves those against the page origin -> ``/assets/xxx.png`` ->
   404, so the preview pane shows a broken image.

   We re-write ONLY relative refs that begin with ``assets/`` to the owning
   API endpoint for the current context:

     * job view  -> /api/jobs/<id>/assets/<name>
     * doc view  -> /api/documents/<id>/assets/<name>

   External URLs, absolute paths and any other relative path are left
   untouched.  The editor text (and copy/export) keeps the raw Markdown.

   Pure + dependency-free so it can be unit-tested under Node via
   ``module.exports``.
*/
"use strict";
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.__g2nAssets = api;
  }
})(typeof self !== "undefined" ? self : this, function () {
  // Only rewrite refs that literally start with "assets/".
  function isAssetRef(name) {
    return typeof name === "string" && name.indexOf("assets/") === 0;
  }

  // kind: "job" -> /api/jobs/<id>/assets/<leaf>
  //       "doc" -> /api/documents/<id>/assets/<leaf>
  // Any name that is not an "assets/..." relative ref is returned unchanged.
  function resolveAssetSrc(name, kind, id) {
    if (!isAssetRef(name)) return name;
    const leaf = name.slice("assets/".length);
    const base =
      kind === "job"
        ? `/api/jobs/${encodeURIComponent(id)}/assets/`
        : `/api/documents/${encodeURIComponent(id)}/assets/`;
    return base + encodeURIComponent(leaf);
  }

  // marked v4 passes (href, title, text) strings to renderer.image; marked
  // v12+ passes a single token object {href, title, text, ...}.  Normalize
  // both shapes into {href, title, text} so the renderer keeps working
  // regardless of which marked version is loaded (issue 06c).
  function normalizeImageArgs(hrefOrToken, title, text) {
    if (hrefOrToken && typeof hrefOrToken === "object") {
      return {
        href: typeof hrefOrToken.href === "string" ? hrefOrToken.href : "",
        title: typeof hrefOrToken.title === "string" ? hrefOrToken.title : null,
        text: typeof hrefOrToken.text === "string" ? hrefOrToken.text : "",
      };
    }
    return {
      href: typeof hrefOrToken === "string" ? hrefOrToken : "",
      title: typeof title === "string" ? title : null,
      text: typeof text === "string" ? text : "",
    };
  }

  // Structure diagrams / flows rendered by the backend follow the issue-02
  // path contract: assets/<doc>-<diagram|flow>-<n>.png (rendered structure,
  // not an uploaded photo).  They get a dedicated figure presentation so a
  // grouped/layered drawing is readable in the reading pane.
  const DIAGRAM_ASSET_RE = /(?:^|\/)[^/]*-(?:diagram|flow)-\d+\.png$/i;

  function isDiagramAssetRef(name) {
    return typeof name === "string" && DIAGRAM_ASSET_RE.test(name);
  }

  function escHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // Wrap a rendered structure diagram in a <figure> with its caption so the
  // reading pane shows the drawing as a distinct, labelled block.  Pure string
  // builder (DOM-free) so it can be unit-tested under Node.  ``alt`` is the
  // diagram caption produced by the renderer (SPEC: caption = alt text).
  function buildDiagramFigure(src, alt, title) {
    const caption = typeof alt === "string" ? alt : "";
    const titleAttr = typeof title === "string" && title
      ? ` title="${escHtml(title)}"` : "";
    const captionHtml = caption
      ? `<figcaption class="g2n-diagram-caption">${escHtml(caption)}</figcaption>`
      : "";
    return `<figure class="g2n-diagram">`
      + `<img src="${escHtml(src)}" alt="${escHtml(caption)}"${titleAttr}`
      + ` tabindex="0" role="button" aria-label="放大查看结构图">`
      + `${captionHtml}</figure>`;
  }

  return {
    isAssetRef: isAssetRef,
    resolveAssetSrc: resolveAssetSrc,
    normalizeImageArgs: normalizeImageArgs,
    isDiagramAssetRef: isDiagramAssetRef,
    buildDiagramFigure: buildDiagramFigure,
  };
});