"""Shared keyword-retrieval engine for local search (P3).

Both the issue-10 PDF search (:mod:`graph2note.pdfsearch`) and the P3 unified
document+PDF search (:mod:`graph2note.unifiedsearch`) index their content with
this module, so the *API shape* of a search — tokens, snippets, postings,
matching, scoring, persisted index files — is defined exactly once.

It stays deliberately small and dependency-free:

- **Tokenisation** supports Chinese, English and mixed queries: ASCII runs are
  lower-cased word tokens; CJK runs are indexed as character bigrams.
- **Index** is a plain inverted postings table (token -> {key: count}) plus a
  per-key length, persisted as JSON under ``<storage>/search/``.
- **Matching** is an AND over distinct tokens (search box) or a ranked OR
  (natural-language questions).
- **Freshness** is a cheap fingerprint over the source records; a changed
  fingerprint means the next search rebuilds, so deleted/stale content can never
  be returned.

No model/LLM call is ever made here.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

INDEX_VERSION = 1
SNIPPET_WIDTH = 72
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_ASCII_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


# ---------------------------------------------------------------------------
# Tokenisation + text helpers
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """Tokenise mixed Chinese/English text into keyword tokens.

    - ASCII word runs -> lower-cased word tokens (``State`` -> ``state``).
    - CJK runs -> character bigrams; a single CJK character stays itself.
    """
    text = text or ""
    tokens: list[str] = []
    for m in _ASCII_RE.finditer(text):
        tokens.append(m.group(0).lower())
    for m in _CJK_RE.finditer(text):
        run = m.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def make_snippet(content: str, tokens: list[str], width: int = SNIPPET_WIDTH) -> str:
    """Return a short window around the earliest token occurrence."""
    if not content:
        return ""
    low = content.lower()
    pos = -1
    for t in tokens:
        p = low.find(t.lower())
        if p != -1 and (pos == -1 or p < pos):
            pos = p
    if pos == -1:
        return content[: width * 2].replace("\n", " ").strip()
    start = max(0, pos - width)
    end = min(len(content), pos + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return (prefix + content[start:end].replace("\n", " ").strip() + suffix)


def content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:16]


def fingerprint(parts: list[str]) -> str:
    """Stable freshness key over the source-record contribution strings."""
    ordered = sorted(parts)
    return hashlib.sha256("\x1e".join(ordered).encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Inverted index primitives
# ---------------------------------------------------------------------------


def build_inverted(entries: list[dict]) -> tuple[dict, dict]:
    """Build ``(postings, lengths)`` from ``{key, text, title?}`` entries.

    ``title`` tokens are added with a weight of 2 so a title match outranks an
    incidental body match, while still never dominating a strong body hit.
    ``lengths`` counts the weighted token total (used for diagnostics only).
    """
    postings: dict[str, dict[str, int]] = {}
    lengths: dict[str, int] = {}
    for entry in entries:
        key = entry["key"]
        tokens = tokenize(entry.get("text") or "")
        title_tokens = tokenize(entry.get("title") or "")
        lengths[key] = len(tokens) + 2 * len(title_tokens)
        for token, weight in _weighted(tokens, title_tokens):
            bucket = postings.setdefault(token, {})
            bucket[key] = bucket.get(key, 0) + weight
    return postings, lengths


def _weighted(tokens: list[str], title_tokens: list[str]):
    for token in tokens:
        yield token, 1
    for token in title_tokens:
        yield token, 2


def match_keys(postings: dict, tokens: list[str], match: str = "all") -> set[str]:
    """Candidate keys for the query tokens (AND by default, OR for questions)."""
    candidate_sets = [set(postings.get(t, {})) for t in tokens]
    if not candidate_sets:
        return set()
    if match == "any":
        return set().union(*candidate_sets)
    return set.intersection(*candidate_sets)


def score_of(postings: dict, key: str, tokens: list[str]) -> int:
    return sum(postings.get(t, {}).get(key, 0) for t in tokens)


def rank_key(hit: dict, *extra: str) -> tuple:
    """Default deterministic ordering: score desc, then the given tie-breakers."""
    return (-hit.get("score", 0),) + tuple(hit.get(k, "") or "" for k in extra)


# ---------------------------------------------------------------------------
# Persisted index helpers
# ---------------------------------------------------------------------------


def search_dir(store) -> Path:
    root = getattr(store, "root", None)
    if root is None:
        raise RuntimeError("document store has no filesystem root")
    return Path(root) / "search"


def index_path_for(store, filename: str) -> Path:
    return search_dir(store) / filename


def write_index(path: Path, index: dict) -> None:
    """Best-effort persist; an unwritable cache dir must never break search."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def read_index(path: Path, version: int = INDEX_VERSION) -> dict | None:
    if not path.is_file():
        return None
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if index.get("version") != version:
        return None
    return index


__all__ = [
    "INDEX_VERSION",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "SNIPPET_WIDTH",
    "tokenize",
    "make_snippet",
    "content_hash",
    "fingerprint",
    "build_inverted",
    "match_keys",
    "score_of",
    "rank_key",
    "search_dir",
    "index_path_for",
    "write_index",
    "read_index",
]
