"""Unified local search over document Markdown + parsed PDF pages (P3).

One index, one search API, two result groups.  The keyword engine (tokens,
snippets, inverted postings, persistence) is the shared
:mod:`graph2note.searchlib`; the PDF-side freshness semantics are the same as
the issue-10 :mod:`graph2note.pdfsearch` index.

What is indexed
---------------

- **Documents** (:mod:`graph2note.store` records without PDF provenance) are
  indexed at *block* level: a Markdown document is split on blank lines and
  heading boundaries, and every block is an index entry.  Matching blocks are
  aggregated back to one result per document (``matched_blocks`` reports how
  many blocks hit), so a document never appears twice in the results.
- **PDF pages** (documents carrying ``pdf_id`` + ``page_index``) are indexed as
  one page entry each, with the original page order and PDF identity preserved.

Freshness
---------

A cheap fingerprint over the whole library (id + ``updated_at`` + latest version
id + current markdown hash) decides whether the persisted/in-memory index is
still valid.  Creating, editing, re-parsing (including R1 repair versions) or
deleting a document changes the fingerprint, so the next search rebuilds from
the library and can never return content for a deleted or stale document.  The
index is persisted under ``<storage>/search/unified-index.json`` and can always
be rebuilt from the library.

No embeddings and no model/LLM call of any kind happens here.
"""

from __future__ import annotations

import re
import threading
import time

from . import searchlib
from .searchlib import DEFAULT_LIMIT, MAX_LIMIT, SNIPPET_WIDTH, tokenize
from .searchlib import content_hash as _content_hash
from .searchlib import make_snippet

__all__ = [
    "INDEX_VERSION",
    "INDEX_FILENAME",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "SNIPPET_WIDTH",
    "split_blocks",
    "build_index",
    "load_index",
    "get_index",
    "store_fingerprint",
    "index_path",
    "search",
]

INDEX_VERSION = 1
INDEX_FILENAME = "unified-index.json"
INDEX_KIND = "unified"

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")

_index_lock = threading.Lock()
_mem_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Markdown block splitting
# ---------------------------------------------------------------------------


def split_blocks(markdown: str) -> list[dict]:
    """Split Markdown into block-level entries (paragraphs / heading sections).

    Blank lines end a block; a heading always starts a new block.  A document
    with no usable text still yields one (empty) block so its title stays
    searchable.
    """
    text = (markdown or "").replace("\r\n", "\n")
    blocks: list[dict] = []
    current: list[str] = []
    heading: str | None = None

    def flush() -> None:
        if current:
            blocks.append({"text": "\n".join(current), "heading": heading})

    for line in text.split("\n"):
        if not line.strip():
            flush()
            current = []
            continue
        if _HEADING_RE.match(line):
            flush()
            current = []
            heading = line.strip().lstrip("#").strip() or None
        current.append(line)
    flush()
    if not blocks:
        blocks = [{"text": "", "heading": None}]
    return blocks


# ---------------------------------------------------------------------------
# Snapshot + index build
# ---------------------------------------------------------------------------


def _pdf_name_from_record(rec: dict) -> str | None:
    title = str(rec.get("title") or "")
    for sep in (" · 第", "·第"):
        if sep in title:
            return title.split(sep, 1)[0].strip() or None
    source = rec.get("source_pdf")
    if source:
        name = str(source).rsplit("/", 1)[-1]
        if name and name != "original.pdf":
            return name
    return None


def _snapshot(store) -> tuple[str, list[dict], dict, int, int]:
    """One pass over the library: fingerprint + entries + live contents + counts.

    ``contents`` maps ``document_id -> current markdown`` from the same pass, so
    a search never has to re-read records it just read for freshness.
    """
    parts: list[str] = []
    entries: list[dict] = []
    contents: dict[str, str] = {}
    document_docs = 0
    page_docs = 0
    for meta in store.list_documents():
        doc_id = meta.get("document_id")
        if not doc_id:
            continue
        rec = store.get_document(doc_id)
        if not rec:
            parts.append(f"{doc_id}\x1fmissing")
            continue
        content = rec.get("current_markdown") or ""
        contents[doc_id] = content
        chash = _content_hash(content)
        versions = meta.get("versions") or []
        last = ""
        if versions and isinstance(versions[-1], dict):
            last = str(versions[-1].get("version_id") or "")
        updated = rec.get("updated_at") or meta.get("updated_at") or ""
        version_id = rec.get("latest_version") or last or None
        parts.append(f"{doc_id}\x1f{updated}\x1f{last}\x1f{chash}")

        pdf_id = rec.get("pdf_id")
        page_index = rec.get("page_index")
        title = rec.get("title") or doc_id
        if pdf_id and page_index is not None:
            page_docs += 1
            entries.append({
                "key": f"pdf:{doc_id}",
                "kind": "pdf_page",
                "document_id": doc_id,
                "block_index": None,
                "title": title,
                "text": content,
                "content_hash": chash,
                "updated_at": updated,
                "version_id": version_id,
                "pdf_id": pdf_id,
                "pdf_name": _pdf_name_from_record(rec),
                "page_index": int(page_index),
                "page_number": rec.get("page_number"),
            })
            continue

        document_docs += 1
        for block_index, block in enumerate(split_blocks(content)):
            entries.append({
                "key": f"doc:{doc_id}:{block_index}",
                "kind": "document",
                "document_id": doc_id,
                "block_index": block_index,
                "title": title,
                "heading": block.get("heading"),
                "text": block.get("text") or "",
                "content_hash": chash,
                "updated_at": updated,
                "version_id": version_id,
                "pdf_id": None,
                "pdf_name": None,
                "page_index": None,
                "page_number": None,
            })
    return (searchlib.fingerprint(parts), entries, contents,
            document_docs, page_docs)


def _index_from_entries(fingerprint: str, entries: list[dict],
                        document_docs: int, page_docs: int) -> dict:
    postings, lengths = searchlib.build_inverted(entries)
    keys = {
        e["key"]: {k: v for k, v in e.items() if k not in ("key", "text")}
        for e in entries
    }
    return {
        "version": INDEX_VERSION,
        "built_at": time.time(),
        "fingerprint": fingerprint,
        "entries": keys,
        "postings": postings,
        "lengths": lengths,
        "indexed_documents": document_docs,
        "indexed_pdf_pages": page_docs,
    }


def _cache_key(store) -> str:
    root = getattr(store, "root", None)
    return f"{INDEX_KIND}:{type(store).__name__}:{root}"


def index_path(store):
    return searchlib.index_path_for(store, INDEX_FILENAME)


def build_index(store, *, persist: bool = True) -> dict:
    """(Re)build the unified index from the current library."""
    fingerprint, entries, _contents, document_docs, page_docs = _snapshot(store)
    index = _index_from_entries(fingerprint, entries, document_docs, page_docs)
    if persist:
        searchlib.write_index(index_path(store), index)
    return index


def load_index(store) -> dict | None:
    try:
        p = index_path(store)
    except RuntimeError:
        return None
    return searchlib.read_index(p, INDEX_VERSION)


def get_index(store, *, force: bool = False) -> dict:
    """Return the fresh index (memory/disk cache reused when still valid)."""
    return _get_index(store, force=force)[0]


def _get_index(store, *, force: bool = False) -> tuple[dict, dict]:
    """Return ``(index, live_contents)`` from a single library snapshot.

    ``live_contents`` comes from the same pass that produced the fingerprint, so
    the search path never re-reads a record it just read for freshness.
    """
    fingerprint, entries, contents, document_docs, page_docs = _snapshot(store)
    key = _cache_key(store)
    if not force:
        with _index_lock:
            cached = _mem_cache.get(key)
        if cached and cached.get("fingerprint") == fingerprint:
            return cached, contents
        persisted = load_index(store)
        if persisted and persisted.get("fingerprint") == fingerprint:
            with _index_lock:
                _mem_cache[key] = persisted
            return persisted, contents
    index = _index_from_entries(fingerprint, entries, document_docs, page_docs)
    searchlib.write_index(index_path(store), index)
    with _index_lock:
        _mem_cache[key] = index
    return index, contents


def store_fingerprint(store) -> str:
    return _snapshot(store)[0]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def _document_hit(entry: dict, body: str, score: int, tokens: list[str],
                  pdf_names: dict | None) -> dict:
    snippet = make_snippet(body, tokens)
    if not snippet:
        snippet = entry.get("title") or ""
    return {
        "kind": "document",
        "document_id": entry["document_id"],
        "title": entry.get("title") or entry["document_id"],
        "block_index": entry.get("block_index"),
        "heading": entry.get("heading"),
        "matched_blocks": 1,
        "score": score,
        "snippet": snippet,
        "version_id": entry.get("version_id"),
        "updated_at": entry.get("updated_at"),
        "review_url": f"/api/documents/{entry['document_id']}",
        "editor_url": f"#doc/{entry['document_id']}",
    }


def _pdf_hit(entry: dict, body: str, score: int, tokens: list[str],
             pdf_names: dict | None) -> dict:
    pdf_id = entry.get("pdf_id")
    pdf_name = None
    if pdf_names:
        pdf_name = pdf_names.get(pdf_id)
    pdf_name = pdf_name or entry.get("pdf_name")
    page_index = int(entry.get("page_index") or 0)
    return {
        "kind": "pdf_page",
        "document_id": entry["document_id"],
        "pdf_id": pdf_id,
        "pdf_name": pdf_name,
        "page_index": page_index,
        "page_number": entry.get("page_number"),
        "title": entry.get("title") or entry["document_id"],
        "score": score,
        "snippet": make_snippet(body, tokens),
        "version_id": entry.get("version_id"),
        "updated_at": entry.get("updated_at"),
        "review_url": f"/api/documents/{entry['document_id']}",
        "source_page_url": f"/api/documents/{entry['document_id']}/source-page",
        "pdf_page_url": f"/api/pdf/{pdf_id}/page/{page_index}",
        "editor_url": f"#doc/{entry['document_id']}",
    }


def search(store, query: str, *, limit: int = DEFAULT_LIMIT, match: str = "all",
           kind: str | None = None, pdf_ids: list[str] | None = None,
           pdf_id: str | None = None, pdf_names: dict | None = None) -> dict:
    """Search document Markdown *and* parsed PDF pages in one call.

    Returns grouped results: ``documents`` (per-document, best block) and
    ``pdf_pages`` (per page).  ``kind`` restricts to one group; ``pdf_id`` /
    ``pdf_ids`` restrict the PDF-page group to a scope.
    """
    q = (query or "").strip()
    tokens = list(dict.fromkeys(tokenize(q)))
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    if not tokens:
        empty = _empty_result(q, store)
        if kind == "document":
            empty["pdf_pages"] = []
        elif kind == "pdf_page":
            empty["documents"] = []
        empty["groups"] = {"documents": empty["documents"],
                           "pdf_pages": empty["pdf_pages"]}
        empty["total"] = len(empty["documents"]) + len(empty["pdf_pages"])
        return empty

    index, contents = _get_index(store)
    entries: dict = index.get("entries", {})
    postings: dict = index.get("postings", {})
    scope = None
    if pdf_ids is not None:
        scope = {str(p) for p in pdf_ids}
    elif pdf_id:
        scope = {str(pdf_id)}

    matched = searchlib.match_keys(postings, tokens, match)

    document_hits: dict[str, dict] = {}
    pdf_hits: list[dict] = []
    seen_pages: set[tuple] = set()
    for key in matched:
        entry = entries.get(key)
        if not entry:
            continue
        if kind is not None and entry.get("kind") != kind:
            continue
        doc_id = entry["document_id"]
        body = contents.get(doc_id)
        if body is None:
            continue  # document vanished since the snapshot: never cite it
        if _content_hash(body) != entry.get("content_hash"):
            continue  # index momentarily stale -> never serve stale content
        score = searchlib.score_of(postings, key, tokens)
        if entry.get("kind") == "pdf_page":
            if scope is not None and str(entry.get("pdf_id")) not in scope:
                continue
            page_key = (entry.get("pdf_id"), entry.get("page_index"))
            if page_key in seen_pages:
                continue
            seen_pages.add(page_key)
            pdf_hits.append(_pdf_hit(entry, body, score, tokens, pdf_names))
        else:
            hit = _document_hit(entry, body, score, tokens, pdf_names)
            existing = document_hits.get(doc_id)
            if existing is None:
                document_hits[doc_id] = hit
            else:
                existing["matched_blocks"] += 1
                if score > existing["score"]:
                    document_hits[doc_id] = hit
                    document_hits[doc_id]["matched_blocks"] = (
                        existing["matched_blocks"])

    documents = sorted(
        document_hits.values(),
        key=lambda h: (-h["score"], -h["matched_blocks"], h["title"],
                       h["document_id"]))[:limit]
    pdf_pages = sorted(
        pdf_hits,
        key=lambda h: (-h["score"], h.get("pdf_name") or "",
                       h.get("page_index") or 0, h["document_id"]))[:limit]

    return _result(q, tokens, documents, pdf_pages, index)


def _empty_result(q: str, store) -> dict:
    try:
        index, _contents = _get_index(store)
    except Exception:
        index = {}
    return _result(q, [], [], [], index)


def _result(q: str, tokens: list[str], documents: list[dict],
            pdf_pages: list[dict], index: dict) -> dict:
    total = len(documents) + len(pdf_pages)
    indexed_documents = int(index.get("indexed_documents") or 0)
    indexed_pdf_pages = int(index.get("indexed_pdf_pages") or 0)
    message = ""
    if not tokens:
        message = "请输入关键词。"
    elif total == 0:
        if indexed_documents == 0 and indexed_pdf_pages == 0:
            message = "文档库还是空的，暂无可检索内容。"
        else:
            message = "没有匹配的内容。"
    return {
        "query": q,
        "tokens": list(tokens),
        "total": total,
        "documents": documents,
        "pdf_pages": pdf_pages,
        "groups": {"documents": documents, "pdf_pages": pdf_pages},
        "indexed_documents": indexed_documents,
        "indexed_pdf_pages": indexed_pdf_pages,
        "message": message,
    }
