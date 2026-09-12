"""Helper for frontend-source assertions (U1 ES-module split).

After U1 the zero-build frontend lives in ``graph2note/webstatic/app.js`` plus
``graph2note/webstatic/js/**`` (and ``assets.js``).  Tests that assert a
behaviour string appears somewhere in the frontend concatenate the sources, so
the assertion never depends on which module owns the line.  This helper asserts
nothing itself.
"""

from __future__ import annotations

from pathlib import Path

import graph2note

WEBSTATIC = Path(graph2note.__file__).parent / "webstatic"


def static_js() -> str:
    """Return every static JS source file concatenated (sorted, stable)."""
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(WEBSTATIC.rglob("*.js"))
    )


def app_entry() -> str:
    """Return only the module entry point served at ``/static/app.js``."""
    return (WEBSTATIC / "app.js").read_text(encoding="utf-8")
