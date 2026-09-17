"""Import-time metadata/reference extraction and persistence (SPW PRR / 02).

The deterministic parser lives in :mod:`graph2note.papers.metadata` /
:mod:`graph2note.papers.references`; this module is the **wiring** layer that
turns a stored paper full text into the P2 metadata slot:

- run the existing P2 parser over the paper text (never a hard external
  dependency; no network, no LLM);
- merge the fresh result over whatever is already stored while **protecting
  fields the user edited by hand** (``provenance.source == "manual"``);
- persist through the existing dual-slot accessors (``set_paper_meta`` /
  ``set_paper_references``) so import, the metadata endpoint and the reading
  view all read the same value;
- report an honest status separate from the import itself: a paper can import
  fine (``done``) while metadata extraction is ``empty`` or ``failed``.

Optional external parsers (an LLM proposal, GROBID) are applied through the
same "fill only empty fields" rule as :mod:`graph2note.papers.enhance`; they are
never required and never run by default.

The whole module is deterministic given the same stored text: running the
extraction twice writes byte-identical slots (idempotent), so a historical
back-fill or a retry is safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from pydantic import BaseModel

from .metadata import FieldProvenance, PaperMeta
from .references import parse_paper_text

__all__ = [
    "ExtractionResult",
    "ExtractionStatus",
    "MANUAL_SOURCE",
    "extract_and_persist",
    "merge_manual_meta",
    "preferred_document_title",
    "run_extraction",
]

#: Provenance source written by a manual correction (see webapp ``_write_paper_meta``).
MANUAL_SOURCE = "manual"

#: One status per paper; ``failed`` never aborts the import.
ExtractionStatus = Literal["ok", "empty", "failed"]

#: The fields a ``PaperMeta`` carries (mirrors ``metadata._META_FIELDS``).
_META_FIELDS = (
    "title", "authors", "year", "venue", "doi", "abstract", "keywords", "source",
)


@dataclass
class ExtractionResult:
    """Outcome of one import-time / on-demand extraction."""

    status: str = "empty"          # ok | empty | failed
    meta: dict = field(default_factory=dict)
    meta_provenance: dict = field(default_factory=dict)
    references: list = field(default_factory=list)
    references_provenance: list = field(default_factory=list)
    preserved: list = field(default_factory=list)   # manual fields kept as-is
    applied: list = field(default_factory=list)     # fields filled by an external parser
    notes: list = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "preserved": list(self.preserved),
            "applied": list(self.applied),
            "notes": list(self.notes),
            "error": self.error,
        }


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _meta_is_empty(meta: dict) -> bool:
    return all(_is_empty(meta.get(field)) for field in _META_FIELDS)


def merge_manual_meta(
    existing_meta: dict | None,
    existing_provenance: dict | None,
    parsed_meta: dict,
    parsed_provenance: dict,
) -> tuple[dict, dict, list[str]]:
    """Overlay a fresh parse while keeping fields the user edited by hand.

    A field is treated as manual when its stored provenance source is
    ``"manual"`` and it currently holds a non-empty value.  Every other field
    is replaced by the fresh deterministic parse (which is what makes a repeat
    run idempotent).  Returns ``(meta, provenance, preserved_fields)``.
    """

    stored = existing_meta if isinstance(existing_meta, dict) else {}
    stored_prov = existing_provenance if isinstance(existing_provenance, dict) else {}
    meta = dict(parsed_meta or {})
    provenance = {key: dict(value) for key, value in (parsed_provenance or {}).items()
                  if isinstance(value, dict)}
    preserved: list[str] = []
    for field_name in _META_FIELDS:
        value = stored.get(field_name)
        prov = stored_prov.get(field_name)
        if not isinstance(prov, dict):
            continue
        if prov.get("source") != MANUAL_SOURCE or _is_empty(value):
            continue
        meta[field_name] = value
        provenance[field_name] = dict(prov)
        preserved.append(field_name)
    if preserved:
        # ``PaperMeta.source`` is the overall channel; a preserved manual edit
        # makes the slot a manual one, exactly like a manual PATCH write does.
        meta["source"] = MANUAL_SOURCE
        provenance["source"] = {
            "source": MANUAL_SOURCE,
            "confidence": "high",
            "evidence": "用户手工修正",
        }
    return meta, provenance, preserved


def run_extraction(
    *,
    fulltext: str,
    front_text: str = "",
    references_text: str = "",
    source: str = "text-layer",
):
    """Run the deterministic P2 parser over stored paper text (may raise).

    Kept as a thin seam so callers/tests can exercise the pure parser without a
    store; :func:`extract_and_persist` wraps it and converts failures to a
    ``failed`` status instead of an exception.
    """

    return parse_paper_text(
        {"full_text": fulltext or "", "front_text": front_text or "",
         "references_text": references_text or ""},
        source=source,
    )


def preferred_document_title(
    fallback: str,
    *,
    fulltext: str,
    front_text: str = "",
    source: str = "text-layer",
) -> str:
    """The extracted paper title when the parse found one, else ``fallback``.

    Import commits the document with this title so the library card, the
    search index and the reading view all show the paper's real title instead
    of the uploaded filename; an extraction failure keeps the filename.
    """

    try:
        document = run_extraction(
            fulltext=fulltext, front_text=front_text,
            references_text="", source=source,
        )
    except Exception:  # noqa: BLE001 - filename is always a valid fallback
        return fallback
    title = str(getattr(document.meta, "title", "") or "").strip()
    return title or fallback


def _normalize_reference(reference: Any) -> dict:
    from .references import PaperReference

    if isinstance(reference, PaperReference):
        return reference.model_dump()
    return PaperReference.model_validate(reference).model_dump()


def _provenance_dicts(items) -> list[dict]:
    out: list[dict] = []
    for item in items or []:
        if hasattr(item, "model_dump"):
            out.append(item.model_dump())
        elif isinstance(item, dict):
            out.append(dict(item))
    return out


def _external_proposal(payload: Any) -> Optional["BaseModel"]:
    """Accept a validated ``MetaProposal`` (or a raw dict) from a caller."""

    from .enhance import MetaProposal, validate_meta_proposal

    if isinstance(payload, MetaProposal):
        return payload
    return validate_meta_proposal(payload)


def extract_and_persist(
    store,
    document_id: str,
    *,
    fulltext: str,
    front_text: str = "",
    references_text: str = "",
    source: str = "text-layer",
    proposal: Any = None,
    proposal_source: str = "vlm",
    proposal_evidence: str = "llm-proposal",
    proposal_label: str = "llm",
    external_references: Any = None,
    external_reference_source: str = "vlm",
    extra_notes: Any = None,
    preserve_manual: bool = True,
) -> ExtractionResult:
    """Extract metadata/references for one stored paper and persist the slots.

    Never raises for parser/transport failures: the status becomes ``failed``
    and the previously stored slot is left untouched, so a retry can be issued
    and the import itself stays successful.
    """

    existing = store.paper_payload(document_id) or {}
    existing_meta = existing.get("meta") if isinstance(existing.get("meta"), dict) else {}
    existing_provenance = (
        existing.get("meta_provenance")
        if isinstance(existing.get("meta_provenance"), dict) else {}
    )
    existing_notes = list(existing.get("notes") or [])
    fallback_references = existing.get("references") or []
    fallback_provenance = existing.get("references_provenance") or []

    try:
        document = run_extraction(
            fulltext=fulltext, front_text=front_text,
            references_text=references_text, source=source,
        )
    except Exception as exc:  # noqa: BLE001 - an import must not fail on this
        return ExtractionResult(
            status="failed",
            meta=dict(existing_meta),
            meta_provenance=dict(existing_provenance),
            references=list(fallback_references),
            references_provenance=list(fallback_provenance),
            notes=existing_notes,
            error=f"{type(exc).__name__}: {exc}",
        )

    meta = document.meta.model_dump()
    provenance = {
        key: value.model_dump()
        for key, value in (document.meta_provenance or {}).items()
    }
    parsed_notes = list(document.notes or [])
    applied: list[str] = []

    proposal_obj = _external_proposal(proposal) if proposal is not None else None
    if proposal_obj is not None:
        from .enhance import apply_meta_proposal
        from .metadata import PaperMetaResult

        base = PaperMetaResult(
            meta=PaperMeta.model_validate(meta),
            provenance={
                key: FieldProvenance.model_validate(value)
                for key, value in provenance.items()
            },
            notes=parsed_notes,
        )
        enhanced, applied = apply_meta_proposal(
            base, proposal_obj, source=proposal_source,
            evidence=proposal_evidence, note_label=proposal_label,
        )
        meta = enhanced.meta.model_dump()
        provenance = {
            key: value.model_dump() for key, value in enhanced.provenance.items()
        }
        parsed_notes = list(enhanced.notes)

    preserved: list[str] = []
    if preserve_manual:
        meta, provenance, preserved = merge_manual_meta(
            existing_meta, existing_provenance, meta, provenance,
        )

    references = [_normalize_reference(item) for item in document.references]
    reference_provenance = _provenance_dicts(document.references_provenance)
    if not references and external_references:
        references = [_normalize_reference(item) for item in external_references]
        reference_provenance = [
            {"index": index, "style": "external", "fragments": 1,
             "notes": [f"source:{external_reference_source}"]}
            for index in range(len(references))
        ]
        parsed_notes.append(f"references:{external_reference_source}")

    notes = list(dict.fromkeys([
        *existing_notes,
        *parsed_notes,
        *list(extra_notes or []),
        *[f"manual-preserved:{name}" for name in preserved],
    ]))

    status = "empty"
    if not _meta_is_empty(meta) or references:
        status = "ok"

    store.set_paper_meta(
        document_id, meta, provenance=provenance,
        source=str(meta.get("source") or source), notes=notes,
    )
    store.set_paper_references(
        document_id, references, provenance=reference_provenance,
    )

    return ExtractionResult(
        status=status,
        meta=meta,
        meta_provenance=provenance,
        references=references,
        references_provenance=reference_provenance,
        preserved=preserved,
        applied=applied,
        notes=notes,
    )
