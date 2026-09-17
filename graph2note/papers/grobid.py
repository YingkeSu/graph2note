"""Optional GROBID seam for academic metadata/reference extraction (SPW PRR / 02).

GROBID is an **optional external service**, never a hard runtime dependency:

- nothing here is imported by the deterministic import path;
- the caller has to opt in explicitly (``{"grobid": true}`` on the extraction
  endpoint / :func:`graph2note.papers.extract.extract_and_persist`) and either
  configure ``GRAPH2NOTE_GROBID_URL`` or inject a transport;
- when no service is configured/reachable the deterministic result is kept and
  an honest ``grobid-unavailable`` note is added — the import and the offline
  parse never fail because of it.

The TEI → fields mapping is a pure function of the XML, so it is exercised
offline against a recorded fixture with no network at all.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from xml.etree import ElementTree

__all__ = [
    "GROBID_ENDPOINT_PATH",
    "GROBID_TIMEOUT",
    "GrobidFields",
    "GrobidUnavailable",
    "extract",
    "fields_to_proposal",
    "grobid_url",
    "is_configured",
    "parse_tei",
    "references_from_fields",
]

#: Standard GROBID REST path for "process full text with references".
GROBID_ENDPOINT_PATH = "/api/processFulltextDocument"

#: Default network budget for one GROBID call (seconds).
GROBID_TIMEOUT = 60.0


class GrobidUnavailable(RuntimeError):
    """Raised when GROBID is not configured, unreachable or returned garbage."""


@dataclass
class GrobidFields:
    """The subset of GROBID's TEI header we consume."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""
    doi: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    references: list[dict] = field(default_factory=list)
    raw_xml: str = ""

    def is_empty(self) -> bool:
        return not any([self.title, self.authors, self.year, self.venue,
                        self.doi, self.abstract, self.keywords, self.references])


# ---------------------------------------------------------------------------
# Pure TEI parsing (offline, deterministic)
# ---------------------------------------------------------------------------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter(node, name: str):
    for child in node.iter():
        if _local(child.tag) == name:
            yield child


def _first(nodes, name: str):
    for node in nodes:
        for found in _iter(node, name):
            return found
    return None


def _text(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def _authors(node) -> list[str]:
    names: list[str] = []
    for author in _iter(node, "author"):
        pers = _first([author], "persName")
        if pers is None:
            continue
        forenames = [_text(child) for child in pers
                     if _local(child.tag) == "forename" and _text(child)]
        surname = _text(_first([pers], "surname"))
        full = re.sub(r"\s+", " ", " ".join([*forenames, surname])).strip()
        if full:
            names.append(full)
    return list(dict.fromkeys(names))


def _year(node) -> Optional[int]:
    for date in _iter(node, "date"):
        candidate = date.get("when") or _text(date)
        match = re.search(r"(1[5-9]\d{2}|20\d{2}|21\d{2})", candidate)
        if match:
            return int(match.group(1))
    return None


def _doi(node) -> str:
    for idno in _iter(node, "idno"):
        if (idno.get("type") or "").upper() == "DOI":
            value = _text(idno)
            if value:
                return value
    return ""


def _reference_entries(root) -> list[dict]:
    references: list[dict] = []
    for list_bibl in _iter(root, "listBibl"):
        for bibl in _iter(list_bibl, "biblStruct"):
            analytic_title = ""
            monogr_title = ""
            for title in _iter(bibl, "title"):
                if title.get("level") == "a" and not analytic_title:
                    analytic_title = _text(title)
                elif title.get("level") == "m" and not monogr_title:
                    monogr_title = _text(title)
                elif not analytic_title:
                    analytic_title = _text(title)
            raw = _text(bibl)
            if not raw:
                continue
            references.append({
                "raw": raw,
                "title": analytic_title or monogr_title,
                "authors": _authors(bibl),
                "year": _year(bibl),
                "doi": _doi(bibl),
                "resolved_document_id": None,
            })
    return references


def parse_tei(xml_text: str) -> GrobidFields:
    """Map a GROBID TEI document to :class:`GrobidFields` (pure function)."""

    try:
        root = ElementTree.fromstring(str(xml_text or ""))
    except ElementTree.ParseError as exc:
        raise GrobidUnavailable(f"GROBID TEI 解析失败：{exc}") from exc

    header = _first([root], "teiHeader")
    source_desc = _first([header] if header is not None else [], "sourceDesc")
    title_stmt = _first([header] if header is not None else [], "titleStmt")

    title = ""
    for node in (source_desc, title_stmt):
        if node is None:
            continue
        for candidate in _iter(node, "title"):
            if candidate.get("type") in (None, "main") and _text(candidate):
                title = _text(candidate)
                break
        if title:
            break
    if not title:
        titles = [t for t in _iter(root, "title") if _text(t)]
        title = _text(titles[0]) if titles else ""

    authors = _authors(header if header is not None else root)
    doi = _doi(source_desc if source_desc is not None else root)
    if not doi:
        doi = _doi(header if header is not None else root)
    year = _year(source_desc if source_desc is not None else root)
    if year is None:
        year = _year(header if header is not None else root)

    abstract = ""
    abstract_node = _first([root], "abstract")
    if abstract_node is not None:
        abstract = _text(abstract_node)
        abstract = re.sub(r"^\s*(?:abstract|摘要)\s*[:：.\-—]?\s*", "",
                          abstract, flags=re.I)

    venue = ""
    monogr = _first([source_desc] if source_desc is not None else [], "monogr")
    if monogr is not None:
        for title_node in _iter(monogr, "title"):
            venue = _text(title_node)
            if venue:
                break
    if not venue:
        venue = _text(_first([source_desc] if source_desc is not None else [],
                             "publisher"))

    keywords = [_text(k) for k in _iter(root, "term")
                if k.get("type") in (None, "keyword") and _text(k)]

    return GrobidFields(
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        abstract=abstract,
        keywords=list(dict.fromkeys(keywords)),
        references=_reference_entries(root),
        raw_xml=str(xml_text or ""),
    )


def fields_to_proposal(fields: GrobidFields) -> dict:
    """A ``MetaProposal``-shaped dict (schema validation happens downstream)."""

    proposal: dict[str, Any] = {}
    if fields.title:
        proposal["title"] = fields.title
    if fields.authors:
        proposal["authors"] = list(fields.authors)
    if fields.year is not None:
        proposal["year"] = fields.year
    if fields.venue:
        proposal["venue"] = fields.venue
    if fields.doi:
        proposal["doi"] = fields.doi
    if fields.abstract:
        proposal["abstract"] = fields.abstract
    if fields.keywords:
        proposal["keywords"] = list(fields.keywords)
    return proposal


def references_from_fields(fields: GrobidFields) -> list[dict]:
    """``PaperReference``-shaped dicts (never a fabricated DOI or link)."""

    return [dict(item) for item in fields.references]


# ---------------------------------------------------------------------------
# Transport seam (injectable; default is a small urllib multipart call)
# ---------------------------------------------------------------------------

#: ``transport(url, data, timeout) -> bytes`` — injected in tests, no network.
Transport = Callable[[str, bytes, float], bytes]


def grobid_url(explicit: Optional[str] = None) -> str:
    import os

    url = (explicit or os.environ.get("GRAPH2NOTE_GROBID_URL") or "").strip()
    return url.rstrip("/")


def is_configured(url: Optional[str] = None) -> bool:
    return bool(grobid_url(url))


def _default_transport(url: str, data: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "multipart/form-data; boundary=graph2note"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def _multipart(pdf_bytes: bytes) -> bytes:
    boundary = "graph2note"
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="input"; filename="paper.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + pdf_bytes + tail


def extract(
    pdf_path: str | Path,
    *,
    url: Optional[str] = None,
    transport: Optional[Transport] = None,
    timeout: float = GROBID_TIMEOUT,
) -> GrobidFields:
    """Call GROBID for one PDF; raise :class:`GrobidUnavailable` on any failure."""

    endpoint = grobid_url(url)
    if transport is None:
        if not endpoint:
            raise GrobidUnavailable("未配置 GROBID 服务（GRAPH2NOTE_GROBID_URL）。")
        transport = _default_transport
        target = endpoint + GROBID_ENDPOINT_PATH
    else:
        target = (endpoint or "http://grobid.invalid") + GROBID_ENDPOINT_PATH
    payload = Path(pdf_path).read_bytes()
    try:
        body = transport(target, _multipart(payload), timeout)
    except GrobidUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - optional service, must degrade
        raise GrobidUnavailable(f"GROBID 调用失败：{type(exc).__name__}") from exc
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    else:
        text = str(body or "")
    if not text.strip():
        raise GrobidUnavailable("GROBID 返回空响应。")
    return parse_tei(text)
