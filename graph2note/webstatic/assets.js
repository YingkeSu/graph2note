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

  return {
    isAssetRef: isAssetRef,
    resolveAssetSrc: resolveAssetSrc,
    normalizeImageArgs: normalizeImageArgs,
  };
});