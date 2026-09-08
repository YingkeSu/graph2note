"""scan-effort ingest: PDF split -> page hashing -> near-dup dedup -> missing alerts.

Productized for issue 09.  Core is dependency-light (numpy + PIL only for
hashing/clustering); PDF splitting additionally requires PyMuPDF (guarded, so
the pure functions stay usable without it).  See ``adapter.py`` for the thin
seam consumed by the issue-03 parse pipeline.
"""

from .engine import ingest_pdfs, load_page_numbers_from_arg, DEFAULT_DEDUP_THRESHOLD
from .model import IngestReport, Page, PageCluster, MissingAlert
from .hash import dhash, phash, hamming, similarity, hash_len
from .cluster import cluster_pages, dedupe, split_cluster, summarize_cluster
from .missing import detect_missing, SequencePageNumberExtractor
from .adapter import ParseInput, report_to_parse_inputs
from .pdf import split_pdf, available as pdf_available, \
    content_fraction, is_low_information
from .store_bridge import hash_page_image, near_duplicate, resolve_merge, \
    ingest_single_page, ingest_report_to_store, split_document_versions

__all__ = [
    "ingest_pdfs",
    "load_page_numbers_from_arg",
    "DEFAULT_DEDUP_THRESHOLD",
    "IngestReport",
    "Page",
    "PageCluster",
    "MissingAlert",
    "dhash",
    "phash",
    "hamming",
    "similarity",
    "hash_len",
    "cluster_pages",
    "dedupe",
    "split_cluster",
    "summarize_cluster",
    "detect_missing",
    "SequencePageNumberExtractor",
    "ParseInput",
    "report_to_parse_inputs",
    "split_pdf",
    "pdf_available",
    "content_fraction",
    "is_low_information",
    "hash_page_image",
    "near_duplicate",
    "resolve_merge",
    "ingest_single_page",
    "ingest_report_to_store",
    "split_document_versions",
]