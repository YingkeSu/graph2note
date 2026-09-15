# Vendored: marked (Markdown preview engine)

X5 localizes the Markdown preview so the app works with no external network
(the AO desktop browser panel is offline).  Before X5 `index.html` loaded
`marked` from `cdn.jsdelivr.net`; the failure path only degraded the preview.

## Provenance

| field | value |
| --- | --- |
| package | `marked` |
| version | **4.3.0** (pinned — do not float) |
| license | MIT (see `marked.LICENSE.md`, copied verbatim from the package) |
| file | `marked.min.js` (UMD build shipped in the npm package root) |
| upstream | <https://github.com/markedjs/marked> · <https://marked.js.org> |
| npm tarball | `https://registry.npmjs.org/marked/-/marked-4.3.0.tgz` |
| tarball integrity | `sha512-PRsaiG84bK+AMvxziE/lCFss8juXjNaWzVbN5tXAm4XjeaS9NAHhop+PjQxz2A9h8Q4M/xGmzP8vqNwy6JeK0A==` (npm `dist.integrity`) |
| tarball shasum (sha1) | `796362821b019f734054582038b116481b456cf3` |
| `marked.min.js` sha256 | `c68075672d976e4777390560baa112194855bd4404b13647da4855aae1f9360c` |
| `marked.min.js` bytes | 49718 |

The file is committed **byte-for-byte unmodified**: its own banner already
carries the version and source (`marked v4.3.0 … (MIT Licensed)
https://github.com/markedjs/marked`), so the sha256 above stays verifiable
against the published package.

## How this copy was obtained (auditable)

```sh
npm pack marked@4.3.0            # -> marked-4.3.0.tgz
# verify: sha512 == dist.integrity above, sha1 == dist.shasum above
tar -xzf marked-4.3.0.tgz package/marked.min.js   # vendored here unchanged
```

The copy formerly served by
`https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js` was verified to be
byte-identical to this file (same sha256, checked at vendoring time), so the
swap from the CDN URL to the local path cannot change rendering behaviour.

## Why 4.3.0 is pinned

`marked` v12+ changed `renderer.image` to take a token object; the app's
renderer (`graph2note/webstatic/js/views/document.js`) uses the v4 string
signature `(href, title, text)` and additionally tolerates the v12+ token
object defensively.  Localizing must not change that pin semantics.

## Updating

Bump the version in exactly two places — this file and the `/static/vendor/`
script tag in `webstatic/index.html` — then re-verify the new sha256 against
the npm tarball.  There is **no build step**: this directory is plain static
assets served by the existing `/static` mount, exactly like the rest of
`webstatic/`.
