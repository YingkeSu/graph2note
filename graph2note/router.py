"""Recognition Router — the single, non-bypassable parsing entry point.

MVP hardcodes Route A (Vision-LLM → Document IR).  Every parse request must
flow through ``RecognitionRouter.recognize``; callers never call the model
directly (SPEC FR-004).

P1 extension seams are declared but NOT implemented here (interface only), so
issues 09/10/11 can plug in without touching the pipeline:

* ``candidate_models``    -> issue 11 multi-version candidates (MVP: [model])
* ``verify_second_model`` -> issue 10 dual-model cross-validation diff
* ``route_b``             -> OCR -> LLM structured path (Route B / Hybrid)

The router also enforces the "never let invalid IR reach the renderer" rule
(FR-005 / SPEC Edge Cases): the model reply is parsed and validated against
the IR schema; on failure it retries up to ``max_retries`` times, then reports
a clear error.  Empty replies to diagram extraction funnel into the degrade
path (source crop) via ``source`` injection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .ir import (
    DocumentIR,
    IRValidationError,
    load_dict_as_ir,
    DiagramBlock,
    FlowBlock,
)


class RouteResult:
    """Outcome of a recognition route call."""

    __slots__ = (
        "document",
        "degraded_block_indices",
        "retries",
        "strategy",
        "raw_content",
        "attempts",
        "warnings",
    )

    def __init__(self, document, degraded_block_indices, retries, strategy,
                 raw_content, attempts, warnings) -> None:
        self.document = document
        self.degraded_block_indices = degraded_block_indices
        self.retries = retries
        self.strategy = strategy
        self.raw_content = raw_content
        self.attempts = attempts  # list of dicts (one per model call)
        self.warnings = warnings  # list[str]


class RecognitionError(RuntimeError):
    """Route exhausted retries and could not produce a valid Document IR."""


class RecognitionRouter(ABC):
    """Unified entry interface (SPEC FR-004)."""

    def __init__(self, model: str) -> None:
        self.model = model

    # -- P1 seams (interface only; not implemented in this slice) -------------
    @property
    def candidate_models(self) -> list[str]:
        """Issue 11: multi-version candidate models.  MVP returns just one."""
        return [self.model]

    def verify_second_model(self, doc: DocumentIR) -> None:  # pragma: no cover
        """Issue 10: dual-model cross-validation diff hook.  Not implemented."""
        raise NotImplementedError("dual-model cross-validation is a P1 issue (10)")

    def route_b(self, image_path: str) -> RouteResult:  # pragma: no cover
        """Issue: OCR -> LLM structured (Route B).  Not implemented."""
        raise NotImplementedError("Route B (OCR) is a P1 strategy")

    # -- required -------------------------------------------------------------
    @abstractmethod
    def recognize(
        self,
        image_path: str,
        *,
        diagram_source: str | None = None,
    ) -> RouteResult:
        """Recognize ``image_path`` into a validated Document IR.

        ``diagram_source`` is the preprocessed image path used to seed the
        degrade path for diagram/flow blocks that lack structured semantics.
        """


def _inject_degrade_source(document: DocumentIR, source: str) -> list[int]:
    """For diagram/flow blocks with no nodes OR no edges, point them at the
    source image so the renderer crops-and-embeds (degrade path).  Returns the
    indices of blocks that were degraded."""
    degraded: list[int] = []
    for i, block in enumerate(document.blocks):
        if isinstance(block, (DiagramBlock, FlowBlock)):
            if (not block.nodes) and (not block.edges):
                if not block.source:
                    block.source = source
                degraded.append(i)
    return degraded


class RouteARouter(RecognitionRouter):
    """Route A: Vision-LLM produces a Document IR directly.

    ``caller(image_path, model) -> (raw_content, meta)`` is injectable for
    offline tests / golden-file reuse.  Default wires the opencode-go gateway.
    """

    def __init__(
        self,
        model: str,
        *,
        caller=None,
        max_retries: int = 2,
        session: str = "graph2note-parse-route-a",
    ) -> None:
        super().__init__(model)
        self._caller = caller
        self.max_retries = max_retries
        self.session = session

    def _call(self, image_path: str, recover: bool = False) -> tuple[str, dict]:
        if self._caller is not None:
            try:
                return self._caller(image_path, self.model, recover=recover)
            except TypeError:  # 2-arg callable (offline tests / stubs)
                return self._caller(image_path, self.model)
        from . import vlm  # local import keeps network out of import path

        return vlm.call_ir(
            image_path, self.model, session=self.session, recover=recover
        )

    def recognize(
        self,
        image_path: str,
        *,
        diagram_source: str | None = None,
    ) -> RouteResult:
        attempts = []
        warnings = []
        raw_content = ""
        document = None
        retries = 0

        for attempt in range(self.max_retries + 1):
            # R4: a retry is a *strategy switch* (tight direct-output prompt,
            # hard timeout) rather than a same-parameters repeat.
            recover = attempt > 0
            try:
                content, meta = self._call(image_path, recover=recover)
            except Exception as exc:
                attempts.append({"attempt": attempt, "error": str(exc)})
                warnings.append(f"model call failed on attempt {attempt}: {exc}")
                if attempt < self.max_retries:
                    continue
                raise RecognitionError(
                    f"model call failed after {attempt + 1} attempts: {exc}"
                ) from exc

            content = (content or "").strip()
            raw_content = content
            attempts.append({"attempt": attempt, "meta": meta})

            if not content:
                warnings.append(f"model returned empty content (attempt {attempt})")
                # empty reply -> degrade: produce empty IR, funnel to crop path
                document = DocumentIR(document_type="note", blocks=[])
                break

            parsed = _parse_to_ir(content)
            if parsed is None:
                warnings.append(
                    f"model reply did not parse into IR JSON (attempt {attempt}); retrying"
                )
                retries += 1
                if attempt < self.max_retries:
                    continue
                raise RecognitionError(
                    "model did not return valid Document IR JSON after "
                    f"{self.max_retries + 1} attempts"
                )
            document = parsed
            break

        # funnel structurally-empty diagrams to the degrade path
        degraded: list[int] = []
        if document is not None and diagram_source:
            degraded = _inject_degrade_source(document, diagram_source)

        return RouteResult(
            document=document,
            degraded_block_indices=degraded,
            retries=retries,
            strategy="route_a",
            raw_content=raw_content,
            attempts=attempts,
            warnings=warnings,
        )


def _parse_to_ir(content: str):
    """Parse + validate raw model text into a DocumentIR, or None."""
    from . import vlm

    obj = vlm.parse_ir_json(content)
    if obj is None:
        return None
    try:
        return load_dict_as_ir(obj)
    except IRValidationError:
        return None


__all__ = [
    "RecognitionRouter",
    "RouteARouter",
    "RecognitionError",
    "RouteResult",
]