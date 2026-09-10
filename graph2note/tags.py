"""Deterministic tag vocabulary and document-tag helpers.

Topics from ``ClassificationScheme`` remain a separate, coarse archive
dimension.  These helpers own the fine-grained, searchable tag vocabulary and
are intentionally independent of the LLM/classification implementation so
recorded outputs can be validated offline before persistence.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class TagError(ValueError):
    """Raised for an empty or invalid tag operation."""


class TagInference(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=32)


def normalize_tag(value: Any) -> str:
    """Normalize whitespace, case, and common separators to one key."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"^#+", "", text).strip()
    text = re.sub(r"[\s_\-./|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    if not text:
        raise TagError("标签不能为空")
    if len(text) > 80:
        raise TagError("标签长度不能超过 80 个字符")
    return text


def validate_tag_inference(raw: Any) -> list[str] | None:
    """Validate a recorded auto-tag output and return normalized candidates."""

    if isinstance(raw, TagInference):
        payload = raw
    else:
        if isinstance(raw, dict):
            raw = raw.get("tags")
        if not isinstance(raw, list):
            return None
        try:
            payload = TagInference.model_validate({"tags": raw})
        except (ValidationError, TypeError, ValueError):
            return None
    out: list[str] = []
    for item in payload.tags:
        if not isinstance(item, str):
            return None
        try:
            canonical = normalize_tag(item)
        except TagError:
            return None
        if canonical not in out:
            out.append(canonical)
    return out


def new_vocabulary() -> dict[str, Any]:
    return {"version": 1, "tags": {}}


def normalize_vocabulary(raw: Any) -> dict[str, Any]:
    """Return a safe vocabulary shape, migrating simple legacy lists."""

    out = new_vocabulary()
    if isinstance(raw, dict) and isinstance(raw.get("tags"), dict):
        source = raw["tags"]
    elif isinstance(raw, dict):
        source = raw
    elif isinstance(raw, list):
        source = {str(item): {} for item in raw}
    else:
        source = {}
    for raw_name, details in source.items():
        try:
            name = normalize_tag(raw_name)
        except TagError:
            continue
        aliases: list[str] = []
        if isinstance(details, dict):
            raw_aliases = details.get("aliases") or []
        elif isinstance(details, list):
            raw_aliases = details
        else:
            raw_aliases = []
        for alias in raw_aliases:
            text = str(alias).strip()
            if not text or text in aliases:
                continue
            try:
                normalize_tag(text)
            except TagError:
                continue
            if text != name:
                aliases.append(text)
        entry = out["tags"].setdefault(name, {"aliases": []})
        for alias in aliases:
            if alias not in entry["aliases"]:
                entry["aliases"].append(alias)
    return out


def _raw_alias(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().lstrip("#").strip()


def resolve_tag(vocabulary: dict[str, Any], value: Any) -> str:
    """Resolve a canonical tag or an existing alias, raising when absent."""

    canonical = normalize_tag(value)
    tags = vocabulary.setdefault("tags", {})
    if canonical in tags:
        return canonical
    for name, details in tags.items():
        for alias in (details or {}).get("aliases", []):
            try:
                if normalize_tag(alias) == canonical:
                    return name
            except TagError:
                continue
    raise TagError(f"词表中不存在标签：{value}")


def ensure_tag(vocabulary: dict[str, Any], value: Any) -> tuple[str, bool]:
    """Reuse a canonical/alias tag or create one with the input as an alias."""

    raw = _raw_alias(value)
    canonical = normalize_tag(raw)
    tags = vocabulary.setdefault("tags", {})
    try:
        existing = resolve_tag(vocabulary, canonical)
    except TagError:
        tags[canonical] = {"aliases": []}
        existing = canonical
        changed = True
    else:
        changed = False
    entry = tags[existing]
    # Keep the human-entered spelling as an alias even when it normalizes to
    # the canonical key (case/separator differences are exactly what the
    # vocabulary is meant to remember for governance).
    if raw and raw != existing and raw not in entry["aliases"]:
        entry["aliases"].append(raw)
        changed = True
    return existing, changed


def canonicalize_tags(vocabulary: dict[str, Any], values: Any) -> tuple[list[str], bool]:
    """Normalize/deduplicate a tag list and register every canonical tag."""

    if values is None:
        values = []
    if not isinstance(values, list):
        raise TagError("tags 必须是数组")
    result: list[str] = []
    changed = False
    for value in values:
        canonical, tag_changed = ensure_tag(vocabulary, value)
        changed = changed or tag_changed
        if canonical not in result:
            result.append(canonical)
        else:
            changed = True
    return result, changed


def vocabulary_entries(vocabulary: dict[str, Any], counts: dict[str, int] | None = None) -> list[dict[str, Any]]:
    counts = counts or {}
    return [
        {
            "tag": name,
            "aliases": sorted((details or {}).get("aliases", []), key=str.casefold),
            "count": int(counts.get(name, 0)),
        }
        for name, details in sorted(vocabulary.get("tags", {}).items(),
                                    key=lambda item: item[0])
    ]


def merge_vocabulary_tags(
    vocabulary: dict[str, Any],
    records: list[dict[str, Any]],
    source: Any,
    target: Any,
) -> tuple[str, str, bool]:
    """Merge ``source`` into ``target`` and update all record memberships."""

    source_name = resolve_tag(vocabulary, source)
    target_name, changed = ensure_tag(vocabulary, target)
    if source_name == target_name:
        return source_name, target_name, changed
    source_entry = vocabulary["tags"].pop(source_name, {"aliases": []})
    target_entry = vocabulary["tags"].setdefault(target_name, {"aliases": []})
    aliases = target_entry.setdefault("aliases", [])
    if source_name not in aliases:
        aliases.append(source_name)
    for alias in source_entry.get("aliases", []):
        if alias != target_name and alias not in aliases:
            aliases.append(alias)
    for record in records:
        tags = list(record.get("tags") or [])
        updated = [target_name if tag == source_name else tag for tag in tags]
        deduped = list(dict.fromkeys(updated))
        if deduped != tags:
            record["tags"] = deduped
    return source_name, target_name, True


def rename_vocabulary_tag(
    vocabulary: dict[str, Any],
    records: list[dict[str, Any]],
    source: Any,
    target: Any,
) -> tuple[str, str, bool]:
    """Rename one canonical label; merge into an existing target if necessary."""

    source_name = resolve_tag(vocabulary, source)
    target_name = normalize_tag(target)
    if source_name == target_name:
        return source_name, target_name, False
    if target_name in vocabulary.get("tags", {}):
        return merge_vocabulary_tags(vocabulary, records, source_name, target_name)
    source_entry = vocabulary["tags"].pop(source_name)
    aliases = list(source_entry.get("aliases", []))
    if source_name not in aliases:
        aliases.append(source_name)
    vocabulary["tags"][target_name] = {"aliases": aliases}
    for record in records:
        record["tags"] = [target_name if tag == source_name else tag
                           for tag in (record.get("tags") or [])]
    return source_name, target_name, True


__all__ = [
    "TagError",
    "TagInference",
    "canonicalize_tags",
    "ensure_tag",
    "merge_vocabulary_tags",
    "new_vocabulary",
    "normalize_tag",
    "normalize_vocabulary",
    "rename_vocabulary_tag",
    "resolve_tag",
    "validate_tag_inference",
    "vocabulary_entries",
]
