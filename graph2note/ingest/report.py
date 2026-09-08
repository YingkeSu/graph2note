"""JSON (de)serialization for IngestReport so reports are inspectable and
re-clustering can run without re-rendering the PDFs (threshold reversible)."""

from __future__ import annotations

import json
from typing import Any

from .model import IngestReport, MissingAlert, Page, PageCluster


def page_to_dict(p: Page) -> dict:
    return {
        "source_pdf": p.source_pdf,
        "page_index": p.page_index,
        "path": p.path,
        "width": p.width,
        "height": p.height,
        "dpi": p.dpi,
        "pg_hash": p.pg_hash,
        "page_number": p.page_number,
        "blank": p.blank,
        "low_information": p.low_information,
    }


def page_from_dict(d: dict) -> Page:
    return Page(
        source_pdf=d["source_pdf"],
        page_index=d["page_index"],
        path=d["path"],
        width=d.get("width", 0),
        height=d.get("height", 0),
        dpi=d.get("dpi", 150),
        pg_hash=d.get("pg_hash", ""),
        page_number=d.get("page_number"),
        blank=d.get("blank", False),
        low_information=d.get("low_information", False),
    )


def report_to_dict(r: IngestReport) -> dict:
    return {
        "source_pdfs": list(r.source_pdfs),
        "hash_method": r.hash_method,
        "threshold": r.threshold,
        "pages": [page_to_dict(p) for p in r.pages],
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "hash_method": c.hash_method,
                "max_distance": c.max_distance,
                "keep": c.keep,
                "page_positions": [
                    r.pages.index(p) for p in c.pages
                ] if c.pages else [],
                "representative_position": (
                    r.pages.index(c.representative) if c.pages else None
                ),
            }
            for c in r.clusters
        ],
        "blank_positions": [r.pages.index(p) for p in r.blank_pages],
        "alerts": [
            {
                "kind": a.kind,
                "message": a.message,
                "missing_numbers": list(a.missing_numbers),
                "observed_numbers": list(a.observed_numbers),
            }
            for a in r.alerts
        ],
    }


def report_from_dict(d: dict) -> IngestReport:
    pages = [page_from_dict(pd) for pd in d["pages"]]
    clusters = []
    for cd in d.get("clusters", []):
        members = [pages[i] for i in cd.get("page_positions", [])]
        c = PageCluster(
            cluster_id=cd.get("cluster_id", 0),
            pages=members,
            hash_method=cd.get("hash_method", "phash"),
            max_distance=cd.get("max_distance", 0),
            keep=cd.get("keep", "latest"),
        )
        clusters.append(c)
    report = IngestReport(
        source_pdfs=list(d.get("source_pdfs", [])),
        pages=pages,
        clusters=clusters,
        blank_pages=[pages[i] for i in d.get("blank_positions", [])],
        alerts=[
            MissingAlert(
                kind=a.get("kind", ""),
                message=a.get("message", ""),
                missing_numbers=list(a.get("missing_numbers", [])),
                observed_numbers=list(a.get("observed_numbers", [])),
            )
            for a in d.get("alerts", [])
        ],
        hash_method=d.get("hash_method", "phash"),
        threshold=d.get("threshold", 0),
    )
    return report


def save_report(report: IngestReport, path: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report_to_dict(report), fh, ensure_ascii=False, indent=2)


def load_report(path) -> IngestReport:
    with open(path, "r", encoding="utf-8") as fh:
        return report_from_dict(json.load(fh))


def summarize(report: IngestReport) -> str:
    """Human-readable multi-line summary (used by CLI + docs)."""
    lines = [
        f"source pdfs      : {len(report.source_pdfs)}",
        f"pages rendered   : {len(report.pages)}",
        f"blank pages      : {len(report.blank_pages)}",
        f"unique pages     : {report.unique_pages}",
        f"candidate versions kept : {report.candidate_versions}",
        f"hash method      : {report.hash_method} (threshold hamming <= {report.threshold})",
    ]
    if report.alerts:
        lines.append("alerts:")
        for a in report.alerts:
            lines.append(f"  - [{a.kind}] {a.message}")
    else:
        lines.append("alerts: none")
    return "\n".join(lines)