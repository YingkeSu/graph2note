"""Local keyword index over parsed PDF page documents (issue 10).

The index is built **only** from library documents that carry PDF provenance
(``pdf_id`` + ``page_index`` from issue 08).  It is a plain keyword index —
no embeddings, no vector store — and is deliberately scope-aware so a query can
target one imported PDF or every imported PDF.

Consistency with the library is guaranteed by a cheap *fingerprint* over the
document list (id + ``updated_at`` + latest version id): adding, editing,
re-parsing or deleting a document changes the fingerprint, so the next search
rebuilds the index and can never return a hit for deleted or stale content
(issue 10 AC4).  The index is persisted under ``<storage>/search/pdf-index.json``
so it survives a restart and can always be rebuilt from the library (AC4).

Tokenisation supports Chinese, English and mixed queries: ASCII runs are
lower-cased word tokens; CJK runs are indexed as character bigrams (a run of
length 1 as the single character).  A query is an AND over its distinct tokens.
No model/LLM call is ever made here.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

INDEX_VERSION = 1
SNIPPET_WIDTH = 72
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_ASCII_RE = re.compile(r"[A-Za-z0-9_]+")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

_index_lock = threading.Lock()
_mem_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Tokenisation + text helpers
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """Tokenise mixed Chinese/English text into keyword tokens (AC2).

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
    """Return a short window around the earliest token occurrence (AC1)."""
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


def _content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Freshness fingerprint + index build/load
# ---------------------------------------------------------------------------


def _snapshot(store) -> tuple[str, list[dict]]:
    """One pass over the library: freshness fingerprint + PDF page documents.

    The fingerprint mixes each document's ``updated_at``, latest version id and
    a hash of its *current markdown*.  The content hash matters because the
    store's timestamps have 1-second resolution, so an edit within the same
    second would otherwise be invisible (issue 10 AC4).
    """
    parts: list[str] = []
    docs: list[dict] = []
    for meta in store.list_documents():
        doc_id = meta.get("document_id")
        if not doc_id:
            continue
        rec = store.get_document(doc_id)
        if not rec:
            parts.append(f"{doc_id}\x1fmissing")
            continue
        content = rec.get("current_markdown") or ""
        chash = _content_hash(content)
        versions = meta.get("versions") or []
        last = ""
        if versions and isinstance(versions[-1], dict):
            last = str(versions[-1].get("version_id") or "")
        updated = rec.get("updated_at") or meta.get("updated_at") or ""
        parts.append(f"{doc_id}\x1f{updated}\x1f{last}\x1f{chash}")
        page_index = rec.get("page_index")
        pdf_id = rec.get("pdf_id")
        if pdf_id and page_index is not None:
            docs.append({
                "document_id": doc_id,
                "pdf_id": pdf_id,
                "page_index": int(page_index),
                "page_number": rec.get("page_number"),
                "title": rec.get("title") or doc_id,
                "version_id": rec.get("latest_version") or last or None,
                "updated_at": updated,
                "content": content,
                "content_hash": chash,
            })
    parts.sort()
    fingerprint = hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()[:24]
    return fingerprint, docs


def store_fingerprint(store) -> str:
    """Cheap freshness key over the whole library (AC4)."""
    return _snapshot(store)[0]


def index_path(store) -> Path:
    root = getattr(store, "root", None)
    if root is None:
        raise RuntimeError("document store has no filesystem root")
    return Path(root) / "search" / "pdf-index.json"


def _index_from_docs(fingerprint: str, docs: list[dict]) -> dict:
    postings: dict[str, dict[str, int]] = {}
    lengths: dict[str, int] = {}
    documents: dict[str, dict] = {}
    for d in docs:
        doc_id = d["document_id"]
        tokens = tokenize(d["content"])
        lengths[doc_id] = len(tokens)
        documents[doc_id] = {
            "pdf_id": d["pdf_id"],
            "page_index": d["page_index"],
            "page_number": d["page_number"],
            "title": d["title"],
            "version_id": d["version_id"],
            "updated_at": d["updated_at"],
            "content_hash": d["content_hash"],
        }
        for t in tokens:
            bucket = postings.setdefault(t, {})
            bucket[doc_id] = bucket.get(doc_id, 0) + 1
    return {
        "version": INDEX_VERSION,
        "built_at": time.time(),
        "fingerprint": fingerprint,
        "documents": documents,
        "postings": postings,
        "lengths": lengths,
    }


def build_index(store, *, persist: bool = True) -> dict:
    """(Re)build the keyword index from the current library (AC4)."""
    fingerprint, docs = _snapshot(store)
    index = _index_from_docs(fingerprint, docs)
    if persist:
        try:
            p = index_path(store)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # an unwritable cache dir must never break search
    return index


def load_index(store) -> dict | None:
    """Load the persisted index, or ``None`` if absent/incompatible."""
    try:
        p = index_path(store)
    except RuntimeError:
        return None
    if not p.is_file():
        return None
    try:
        index = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if index.get("version") != INDEX_VERSION:
        return None
    return index


def _cache_key(store) -> str:
    root = getattr(store, "root", None)
    return f"{type(store).__name__}:{root}"


def get_index(store, *, force: bool = False) -> dict:
    """Return a fresh index, reusing the memory/disk cache when still valid."""
    fingerprint, docs = _snapshot(store)
    key = _cache_key(store)
    if not force:
        with _index_lock:
            cached = _mem_cache.get(key)
        if cached and cached.get("fingerprint") == fingerprint:
            return cached
        persisted = load_index(store)
        if persisted and persisted.get("fingerprint") == fingerprint:
            with _index_lock:
                _mem_cache[key] = persisted
            return persisted
    index = _index_from_docs(fingerprint, docs)
    try:
        p = index_path(store)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    with _index_lock:
        _mem_cache[key] = index
    return index


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search(store, query: str, *, pdf_id: str | None = None,
           limit: int = DEFAULT_LIMIT) -> dict:
    """Keyword search over parsed PDF pages, optionally scoped to one PDF (AC1).

    Returns ``{query, tokens, pdf_id, total, hits, indexed_documents, message}``.
    A hit carries the source PDF identity, the *original page order*
    (``page_index`` / ``page_number`` from provenance), the content version and
    both the review-document and original-page URLs (AC3).
    """
    q = (query or "").strip()
    tokens = list(dict.fromkeys(tokenize(q)))
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    if not tokens:
        return {
            "query": q, "tokens": [], "pdf_id": pdf_id, "total": 0,
            "hits": [], "indexed_documents": 0,
            "message": "请输入关键词。",
        }

    index = get_index(store)
    documents: dict = index.get("documents", {})
    postings: dict = index.get("postings", {})

    indexed_in_scope = sum(
        1 for d in documents.values()
        if not pdf_id or d.get("pdf_id") == pdf_id
    )

    candidate_sets = [set(postings.get(t, {})) for t in tokens]
    ids = set.intersection(*candidate_sets) if candidate_sets else set()
    if pdf_id:
        ids = {i for i in ids if documents.get(i, {}).get("pdf_id") == pdf_id}

    hits = []
    for doc_id in ids:
        meta = documents.get(doc_id) or {}
        rec = store.get_document(doc_id)
        if not rec:
            continue  # belt-and-braces: never cite a deleted document (AC4)
        # current content is authoritative for the snippet even if the index
        # were momentarily stale
        if _content_hash(rec.get("current_markdown") or "") != meta.get("content_hash"):
            continue
        content = rec.get("current_markdown") or ""
        score = sum(postings.get(t, {}).get(doc_id, 0) for t in tokens)
        page_index = int(meta.get("page_index", rec.get("page_index")))
        hits.append({
            "document_id": doc_id,
            "pdf_id": meta.get("pdf_id") or rec.get("pdf_id"),
            "page_index": page_index,
            "page_number": meta.get("page_number", rec.get("page_number")),
            "title": meta.get("title") or rec.get("title"),
            "version_id": meta.get("version_id") or rec.get("latest_version"),
            "score": score,
            "snippet": make_snippet(content, tokens),
            # complete paths: review document + original PDF page (AC1)
            "review_url": f"/api/documents/{doc_id}",
            "source_page_url": f"/api/documents/{doc_id}/source-page",
            "pdf_page_url": (
                f"/api/pdf/{meta.get('pdf_id') or rec.get('pdf_id')}"
                f"/page/{page_index}"
            ),
        })

    hits.sort(key=lambda h: (-h["score"], h["page_index"], h["document_id"]))
    total = len(hits)
    hits = hits[:limit]

    message = ""
    if not hits:
        if indexed_in_scope == 0:
            message = (
                "该 PDF 尚无已解析页可检索（可能仍在导入）。"
                if pdf_id else "尚无已解析的 PDF 内容可检索。"
            )
        else:
            message = "没有匹配的内容。"
    elif pdf_id and indexed_in_scope == 0:
        message = "该 PDF 尚无已解析页可检索（可能仍在导入）。"

    return {
        "query": q,
        "tokens": tokens,
        "pdf_id": pdf_id,
        "total": total,
        "hits": hits,
        "indexed_documents": indexed_in_scope,
        "message": message,
    }


__all__ = [
    "INDEX_VERSION",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "tokenize",
    "make_snippet",
    "store_fingerprint",
    "index_path",
    "build_index",
    "load_index",
    "get_index",
    "search",
]
