"""Deterministic diagram rendering for the Manuscript Compiler (issue 05).

Productized from Spike 3 (see ``spike3/`` for the original evidence).

Pipeline: a ``diagram``/``flow`` block carries structured ``nodes``/``edges``
semantics.  This package turns those semantics into a deterministic PNG asset:

* preferred engine: graphviz/dot (better auto-layout, zero node overlap on
  cycles) when both the python ``graphviz`` package and the ``dot`` binary are
  available;
* fallback: a hand-rolled layered matplotlib renderer (pure-Python, no system
  dependency);
* degradation: when the block has no structured semantics but references an
  original image (``source``), crop the non-background region and embed it -
  no OCR/text pipeline, so it cannot produce mojibake.

Both engines satisfy FR-020: the same semantics always render byte-identical.
"""

from .engine import (
    engines_available,
    graphviz_available,
    render_to_png,
    render_structured,
    RenderOutcome,
)
from .degrade import crop_image

__all__ = [
    "engines_available",
    "graphviz_available",
    "render_to_png",
    "render_structured",
    "RenderOutcome",
    "crop_image",
]
