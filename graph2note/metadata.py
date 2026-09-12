"""Document-level metadata for the Knowledge Workspace.

The parser produces content versions, while this module owns the small amount
of metadata that describes the document independently of a particular parse.
The functions are deliberately deterministic and offline-safe: EXIF is read
locally and date inference uses a validated Markdown seam that can later be
replaced by a text-model adapter without changing the storage/API contract.
"""

from __future__ import annotations

from datetime import date, datetime
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


TIME_FIELDS = ("capture_time", "document_time", "import_time", "modified_time")
WORKSPACE_FIELDS = ("needs_organization",)
_CONFIDENCES = ("high", "medium", "low")
_DATE_KEYS = ("date", "document_date", "document_time", "created", "created_at", "手稿日期")


class DateInference(BaseModel):
    """Schema for a date inference result before it is persisted."""

    date: date
    confidence: Literal["high", "medium", "low"]
    evidence: str = Field(min_length=1, max_length=400)


def _slot(
    value: str | None = None,
    *,
    source: str = "none",
    confidence: str | None = None,
    evidence: str | None = None,
    manual: bool = False,
) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "confidence": confidence,
        "evidence": evidence,
        "manual": bool(manual),
    }


def _flag(value: Any) -> bool:
    """Normalize a legacy workspace flag without making old records fail."""

    if isinstance(value, dict):
        value = value.get("value", value.get("enabled"))
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on", "待整理"}
    return False


def _strict_flag(value: Any, field: str) -> bool:
    """Validate a user-supplied workspace flag before persisting it."""

    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "待整理"}:
            return True
        if normalized in {"0", "false", "no", "off", "已整理", ""}:
            return False
    raise ValueError(f"{field} 必须是布尔值")


def _date_from_text(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    # Normalize the common handwritten/Markdown date separators while keeping
    # the resulting value strict (e.g. 2024-02-30 is rejected below).
    match = re.search(
        r"(?<!\d)(?P<year>19\d{2}|20\d{2})\s*(?:[-/.年])\s*"
        r"(?P<month>\d{1,2})\s*(?:[-/.月])\s*(?P<day>\d{1,2})\s*日?",
        text,
    )
    if not match and re.fullmatch(r"(?:19|20)\d{6}", text):
        match = re.match(r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})", text)
    if not match:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except (TypeError, ValueError):
        return None


def _datetime_from_exif(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    # EXIF normally uses ``YYYY:MM:DD HH:MM:SS``.  Accept ISO as well for
    # synthetic fixtures and cameras that already emit a normalized value.
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).isoformat(timespec="seconds")
        except ValueError:
            pass
    return None


def _normalize_timestamp(value: Any, *, field: str) -> str | None:
    if value is None or value == "":
        return None
    if field == "document_time":
        parsed = _date_from_text(value)
        return parsed.isoformat() if parsed else None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    text = str(value).strip()
    if not text:
        return None
    # A date-only value is valid input for the system fields too; normalize it
    # to midnight so persisted timestamps retain one predictable shape.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.isoformat(timespec="seconds")
    except ValueError:
        parsed_date = _date_from_text(text)
        return parsed_date.isoformat() if parsed_date else None


def validate_date_inference(raw: Any) -> dict[str, Any] | None:
    """Validate an external inference payload and return a storage slot.

    Invalid, missing, or low-quality model output returns ``None``.  Callers
    can therefore safely keep an existing value instead of partially writing a
    malformed date.
    """

    if raw is None:
        return None
    if isinstance(raw, DateInference):
        candidate = raw
    else:
        if not isinstance(raw, dict):
            return None
        value = raw.get("date")
        if value is None:
            value = raw.get("document_time", raw.get("value"))
        candidate = {"date": value, "confidence": raw.get("confidence"),
                     "evidence": raw.get("evidence")}
        try:
            candidate = DateInference.model_validate(candidate)
        except (ValidationError, TypeError, ValueError):
            return None
    return _slot(
        candidate.date.isoformat(),
        source="inferred",
        confidence=candidate.confidence,
        evidence=candidate.evidence.strip(),
        manual=False,
    )


def _date_candidate(text: str, start: int, end: int, confidence: str) -> dict[str, Any] | None:
    parsed = _date_from_text(text[start:end])
    if parsed is None:
        return None
    evidence_start = max(0, start - 48)
    evidence_end = min(len(text), end + 48)
    evidence = re.sub(r"\s+", " ", text[evidence_start:evidence_end]).strip()
    return validate_date_inference({
        "date": parsed.isoformat(),
        "confidence": confidence,
        "evidence": evidence,
    })


def infer_document_time(markdown: str | None) -> dict[str, Any] | None:
    """Infer a document date from front matter/headings/body, offline.

    The precedence is intentionally conservative: explicit front matter wins,
    then a heading/early line, then the first date anywhere in the document.
    The returned object is schema-validated before it can reach the store.
    """

    text = str(markdown or "")
    if not text.strip():
        return None

    date_pattern = (
        r"(?<!\d)(?:19\d{2}|20\d{2})\s*(?:[-/.年])\s*\d{1,2}"
        r"\s*(?:[-/.月])\s*\d{1,2}\s*日?"
    )
    # Explicit Markdown/front-matter fields are the strongest evidence.
    field_re = re.compile(
        r"(?im)^\s*(?:date|document_date|document_time|created|created_at|手稿日期)"
        r"\s*:\s*(?P<value>[^#\n]+)"
    )
    for match in field_re.finditer(text):
        value = match.group("value")
        value_match = re.search(date_pattern, value)
        if value_match:
            start = match.start("value") + value_match.start()
            end = match.start("value") + value_match.end()
            result = _date_candidate(text, start, end, "high")
            if result:
                return result

    # Headings and the first few non-empty lines commonly contain page dates.
    line_offset = 0
    for line_number, line in enumerate(text.splitlines()[:12]):
        stripped = line.strip()
        if stripped and (line_number < 8 or stripped.startswith("#")):
            for match in re.finditer(date_pattern, line):
                result = _date_candidate(text, line_offset + match.start(),
                                         line_offset + match.end(), "high")
                if result:
                    return result
        line_offset += len(line) + 1

    match = re.search(date_pattern, text)
    if match:
        # A date buried in body text is still useful, but visibly less certain.
        return _date_candidate(text, match.start(), match.end(), "medium")
    return None


# U2: card titles come from the Markdown body, not the uploaded filename.
_ATX_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<text>.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")
MAX_HEADLINE = 200


def extract_headline(markdown: str | None) -> str:
    """Return the document's display title from its Markdown body.

    Uses the first non-empty line (ATX ``#`` markers stripped), skipping fenced
    code blocks so a code sample never becomes the card title.  Returns ``""``
    when the document has no usable line, which lets callers fall back to the
    filename without inventing a title.  Pure function: the U2 Library card and
    its tests share this one implementation.
    """

    text = str(markdown or "")
    if not text.strip():
        return ""

    in_fence = False
    for raw in text.splitlines():
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = raw.strip()
        if not line:
            continue
        heading = _ATX_HEADING_RE.match(line)
        value = heading.group("text").strip() if heading else line
        if value:
            return value[:MAX_HEADLINE]
    return ""


def extract_capture_time(image_path: str | Path | None) -> dict[str, Any]:
    """Read the best available local EXIF timestamp without failing parsing."""

    labels = {
        36867: "DateTimeOriginal",
        36868: "DateTimeDigitized",
        306: "DateTime",
    }
    try:
        from PIL import Image

        if image_path is None:
            raise FileNotFoundError
        with Image.open(image_path) as image:
            exif = image.getexif()
            for tag, label in labels.items():
                value = _datetime_from_exif(exif.get(tag))
                if value:
                    return _slot(value, source="exif", confidence="high",
                                 evidence=label)
    except Exception:
        # Missing EXIF, an unsupported image, or a deleted original must never
        # make the parse fail.  The slot remains explicit for the UI.
        pass
    return _slot(source="none", evidence="未读取到 EXIF 拍摄时间")


def normalize_metadata(raw: Any, *, aliases: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize old/new record metadata into the stable public shape."""

    aliases = aliases or {}
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for field in TIME_FIELDS:
        value = raw.get(field)
        if isinstance(value, dict):
            value = dict(value)
            normalized = _normalize_timestamp(value.get("value"), field=field)
            value["value"] = normalized
            value["source"] = str(value.get("source") or ("manual" if value.get("manual") else "none"))
            confidence = value.get("confidence")
            value["confidence"] = confidence if confidence in _CONFIDENCES else None
            evidence = value.get("evidence")
            value["evidence"] = str(evidence) if evidence else None
            value["manual"] = bool(value.get("manual") or value["source"] == "manual")
            out[field] = value
        else:
            legacy = aliases.get(field)
            normalized = _normalize_timestamp(value if value is not None else legacy,
                                              field=field)
            out[field] = _slot(normalized, source="legacy" if normalized else "none",
                                confidence=None, evidence="旧记录回填" if normalized else None)
    raw_flag = raw.get("needs_organization")
    if raw_flag is None:
        raw_flag = aliases.get("needs_organization")
    out["needs_organization"] = _flag(raw_flag)
    out["effective_time"] = select_effective_time(out)
    return out


def ensure_record_metadata(
    record: dict[str, Any],
    *,
    original_path: str | Path | None = None,
    markdown: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Backfill missing metadata on an old record and report whether it changed."""

    before = record.get("metadata")
    aliases = {field: record.get(field) for field in TIME_FIELDS}
    aliases["needs_organization"] = record.get(
        "needs_organization", record.get("inbox", False)
    )
    metadata = normalize_metadata(before, aliases=aliases)
    if not metadata["import_time"]["value"]:
        metadata["import_time"] = _slot(
            _normalize_timestamp(record.get("created_at"), field="import_time"),
            source="system",
            evidence="首次导入时间（兼容旧记录）",
        )
    if not metadata["modified_time"]["value"]:
        metadata["modified_time"] = _slot(
            _normalize_timestamp(record.get("updated_at") or record.get("created_at"),
                                 field="modified_time"),
            source="system",
            evidence="记录更新时间（兼容旧记录）",
        )
    if not metadata["capture_time"]["value"] and original_path:
        metadata["capture_time"] = extract_capture_time(original_path)
    if not metadata["document_time"]["value"] and not metadata["document_time"].get("manual"):
        inferred = infer_document_time(markdown if markdown is not None else record.get("current_markdown"))
        if inferred:
            metadata["document_time"] = inferred
    metadata["effective_time"] = select_effective_time(metadata)
    changed = before != metadata
    sync_record_metadata(record, metadata)
    return record, changed


def merge_record_metadata(
    record: dict[str, Any],
    *,
    markdown: str | None,
    original_path: str | Path | None,
    import_time: str,
    modified_time: str,
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge parse-time metadata while preserving manual corrections."""

    record, _ = ensure_record_metadata(record, original_path=original_path,
                                       markdown=markdown)
    metadata = normalize_metadata(record.get("metadata"), aliases=record)
    candidate = candidate if isinstance(candidate, dict) else {}

    candidate_capture = candidate.get("capture_time")
    if not metadata["capture_time"].get("manual"):
        if isinstance(candidate_capture, dict) and candidate_capture.get("value"):
            metadata["capture_time"] = normalize_metadata(
                {"capture_time": candidate_capture}
            )["capture_time"]
        elif not metadata["capture_time"].get("value"):
            metadata["capture_time"] = extract_capture_time(original_path)

    candidate_document = candidate.get("document_time")
    if not metadata["document_time"].get("manual"):
        if isinstance(candidate_document, dict) and candidate_document.get("value"):
            metadata["document_time"] = normalize_metadata(
                {"document_time": candidate_document}
            )["document_time"]
        elif not metadata["document_time"].get("value"):
            inferred = infer_document_time(markdown)
            if inferred:
                metadata["document_time"] = inferred

    if not metadata["import_time"].get("value"):
        metadata["import_time"] = _slot(import_time, source="system",
                                         evidence="首次导入时间")
    # ``modified_time`` follows content parsing/editing, not metadata-only
    # corrections.  This function is called by a new parse/version commit.
    metadata["modified_time"] = _slot(modified_time, source="system",
                                       evidence="最近一次内容解析")
    metadata["effective_time"] = select_effective_time(metadata)
    sync_record_metadata(record, metadata)
    return record


def apply_metadata_updates(
    record: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Apply user corrections to editable date fields.

    Import and modified times are system-owned.  ``document_time`` and
    ``capture_time`` accept a date/time string (or ``{"value": ...}``) and
    become manual slots, so later reparses/backfills cannot overwrite them.
    """

    metadata = normalize_metadata(record.get("metadata"), aliases=record)
    for field in ("document_time", "capture_time"):
        if field not in updates:
            continue
        raw = updates[field]
        if isinstance(raw, dict):
            raw = raw.get("value")
        normalized = _normalize_timestamp(raw, field=field)
        if raw not in (None, "") and normalized is None:
            raise ValueError(f"{field} 不是合法时间值")
        metadata[field] = _slot(
            normalized,
            source="manual",
            confidence="high" if normalized else None,
            evidence="用户手工修正" if normalized else "用户清除",
            manual=True,
        )
    flag_updates = [
        key for key in ("needs_organization", "inbox", "pending_organization", "pending")
        if key in updates
    ]
    if flag_updates:
        key = "needs_organization" if "needs_organization" in updates else flag_updates[0]
        metadata["needs_organization"] = _strict_flag(updates[key], key)
    forbidden = set(updates) - {"document_time", "capture_time", *flag_updates}
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise ValueError(f"以下时间字段由系统维护，不能手工修改：{names}")
    metadata["effective_time"] = select_effective_time(metadata)
    sync_record_metadata(record, metadata)
    return record


def select_effective_time(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Return the timestamp used by workspace views.

    Priority is the PRD contract: manual document date (represented by the
    document slot) > inferred document date > capture > import.
    """

    for field in ("document_time", "capture_time", "import_time"):
        slot = metadata.get(field) or {}
        if slot.get("value"):
            return {
                "field": field,
                "value": slot["value"],
                "source": slot.get("source") or "none",
                "confidence": slot.get("confidence"),
                "evidence": slot.get("evidence"),
            }
    return None


def sync_record_metadata(record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Store the canonical object and convenient scalar aliases on a record."""

    record["metadata"] = metadata
    for field in TIME_FIELDS:
        record[field] = (metadata.get(field) or {}).get("value")
    record["needs_organization"] = bool(metadata.get("needs_organization"))
    record["effective_time"] = metadata.get("effective_time")
    return record


__all__ = [
    "TIME_FIELDS",
    "WORKSPACE_FIELDS",
    "DateInference",
    "apply_metadata_updates",
    "ensure_record_metadata",
    "extract_capture_time",
    "extract_headline",
    "infer_document_time",
    "merge_record_metadata",
    "normalize_metadata",
    "select_effective_time",
    "sync_record_metadata",
    "validate_date_inference",
]
