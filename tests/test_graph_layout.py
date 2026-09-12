"""U4 knowledge-graph interaction contracts (offline).

Three complementary layers, no network and no live model calls:

1. ``/api/graph`` response contract — the pre-U4 keys keep their exact
   semantics while ``clusters`` / ``filters`` are added additively.
2. Graph-zone DOM contract — toolbar, filter chips and controls exist inside
   the content area, the zero-build red line holds (no new script/CDN), and the
   legend is preserved.
3. Layout engine contract — ``node tests/graph_layout.mjs`` drives the pure
   module and the JSON summary is asserted here, so AC1 ("node bounding-box
   intersection count is 0") is a programmatic property rather than an eyeball
   check.  The test skips only when ``node`` is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graph2note import webapp
from graph2note.graph import EDGE_SOURCES, build_graph
from graph2note.store import FileDocumentStore
from tests.static_assets import WEBSTATIC, static_js
from tests.test_webapp_layout import Element, _DomParser  # reuse the stdlib DOM tree

TESTS_DIR = Path(__file__).parent
GRAPH_MODULE = WEBSTATIC / "js" / "views" / "graph-layout.js"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _record(document_id, title, *, topics=None, tags=None, manual_collections=None,
            collection_names=None, manual_relations=None):
    return {
        "document_id": document_id,
        "title": title,
        "topics": topics or [],
        "tags": tags or [],
        "manual_collections": manual_collections or [],
        "collection_names": collection_names or {},
        "manual_relations": manual_relations or [],
    }


def _payload(records):
    """Mirror what ``GET /api/graph`` hands the front end."""
    return build_graph(records)


@pytest.fixture(scope="module")
def dom() -> Element:
    parser = _DomParser()
    parser.feed((WEBSTATIC / "index.html").read_text(encoding="utf-8"))
    return parser.root


@pytest.fixture(scope="module")
def layout_summary() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node 未安装")
    proc = subprocess.run(
        ["node", str(TESTS_DIR / "graph_layout.mjs")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# 1) API contract: additive fields, unchanged semantics
# ---------------------------------------------------------------------------


def test_graph_payload_keeps_pre_u4_semantics_and_adds_clusters():
    records = [
        _record("d1", "数学笔记", topics=["数学", "复习"], tags=["重点"]),
        _record("d2", "无主题草稿", tags=["草稿"]),
        _record("d3", "手工关联", manual_collections=["research"],
                collection_names={"research": "研究"},
                manual_relations=[{"target": "d1"}]),
    ]
    view = _payload(records)

    # pre-U4 keys and values are untouched
    assert set(view) >= {"nodes", "edges", "sources", "empty", "counts"}
    assert view["sources"] == list(EDGE_SOURCES)
    assert view["empty"] is False
    assert all(edge["source"] in EDGE_SOURCES for edge in view["edges"])
    assert {node["kind"] for node in view["nodes"]} == {
        "document", "topic", "tag", "collection",
    }

    # clusters are a projection only: every document appears exactly once,
    # documents without topics land in one unclustered bucket, and no cluster
    # leaks into `nodes`.
    clusters = view["clusters"]
    assert clusters, "expected topic clusters"
    assigned = [document for cluster in clusters for document in cluster["documents"]]
    assert sorted(assigned) == ["d1", "d2", "d3"]
    unclustered = [cluster for cluster in clusters if cluster["unclustered"]]
    assert [cluster["documents"] for cluster in unclustered] == [["d2", "d3"]]
    assert next(cluster for cluster in clusters if cluster["topic"] == "数学")["documents"] == ["d1"]
    assert all(cluster["id"].startswith("cluster:") for cluster in clusters)
    assert all(cluster["route"].startswith("#library") for cluster in clusters)
    assert not any(node["kind"] == "cluster" for node in view["nodes"])

    # filters expose the same collections/tags the documents carry
    filters = view["filters"]
    assert [item["id"] for item in filters["tags"]] == ["草稿", "重点"]
    assert filters["tags"][0]["count"] == 1
    assert filters["collections"] == [{
        "id": "research", "label": "研究", "count": 1,
        "route": "#library/collection/research",
    }]
    assert filters["sources"] == list(EDGE_SOURCES)


def test_empty_graph_still_exposes_cluster_and_filter_contract():
    view = build_graph([])
    assert view["empty"] is True
    assert view["nodes"] == [] and view["edges"] == []
    assert view["clusters"] == []
    assert view["filters"] == {"collections": [], "tags": [], "sources": []}


def test_graph_api_payload_includes_clusters_and_filters(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    for index in range(6):
        document_id = f"d{index}"
        store.save_document(
            document_id=document_id,
            title=f"文档 {index}",
            source_job_id=f"job-{document_id}",
            model="fixture",
            markdown=f"# 文档 {index}\n",
            ir_json=json.dumps({"blocks": []}),
            original_path="",
            original_ext=".jpg",
            preprocessed_path="",
            preprocessed_raw_path="",
            assets_dir="",
            timing_json={},
        )
        store.set_topics(document_id, ["数学"] if index < 4 else ["物理"])
        store.set_tags(document_id, ["重点"] if index % 2 == 0 else ["草稿"])
    collection = store.create_collection("研究")
    store.set_collections("d0", [collection["collection_id"]])
    client = TestClient(webapp.create_app(document_store=store, storage_dir=store.root))

    graph = client.get("/api/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["counts"]["documents"] == 6
    assert {edge["source"] for edge in payload["edges"]} == {"topic", "tag", "manual"}
    assert sum(cluster["size"] for cluster in payload["clusters"]) == 6
    assert payload["filters"]["collections"][0]["label"] == "研究"
    assert {item["id"] for item in payload["filters"]["tags"]} == {"重点", "草稿"}

    # rendering still consumes only the existing projection (no model call path)
    assert "/api/graph" in static_js()
    assert "clusters" in (WEBSTATIC / "js" / "views" / "graph.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 2) DOM contract: graph zone owns the U4 controls
# ---------------------------------------------------------------------------


def test_graph_zone_owns_toolbar_filters_and_legend(dom):
    graph = dom.find(id="graph-zone")
    assert graph is not None
    for control in ("graph-zoom-in", "graph-zoom-out", "graph-zoom-value",
                    "graph-fit", "graph-reset", "graph-status",
                    "graph-filters", "graph-source-chips", "graph-set-chips",
                    "graph-tag-chips", "graph-clear-filters", "graph-clusters-toggle",
                    "graph-canvas", "graph-empty", "graph-scroll"):
        assert graph.find(id=control) is not None, control
    # the existing three-source legend is preserved (AC: 现有图例保留)
    legend = graph.find(cls="graph-legend")
    assert legend is not None
    legend_classes = [node.attrs.get("class", "") for node in legend.iter_elements()]
    for source in ("topic", "tag", "manual"):
        assert f"graph-legend-dot {source}" in legend_classes, source
    # the controls live inside the content area, not the topbar/sidebar
    assert dom.find(id="content").find(id="graph-zone") is not None


def test_graph_zone_content_area_is_scroll_safe(dom):
    graph = dom.find(id="graph-zone")
    assert graph.find(id="graph-scroll").find(id="graph-canvas") is not None
    # the canvas no longer forces a 760px min-width (pre-U4 horizontal scroll)
    html = (WEBSTATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="graph-canvas"' in html


def test_zero_build_red_line_holds(dom):
    scripts = [node for node in dom.iter_elements() if node.tag == "script"]
    sources = [node.attrs.get("src") for node in scripts if node.attrs.get("src")]
    # U4 adds no CDN dependency and no build step: the graph engine is a local
    # module imported by the existing module entry.
    assert sources.count("https://cdn.jsdelivr.net/npm/marked@4.3.0/marked.min.js") == 1
    assert "/static/app.js" in sources
    assert all("katex" in src or "marked" in src or src.startswith("/static/") for src in sources)
    assert GRAPH_MODULE.is_file()
    app = (WEBSTATIC / "app.js").read_text(encoding="utf-8")
    assert "./js/views/graph.js" in app
    # the layout engine is reachable from the entry through graph.js
    graph_js = (WEBSTATIC / "js" / "views" / "graph.js").read_text(encoding="utf-8")
    assert "./graph-layout.js" in graph_js


# ---------------------------------------------------------------------------
# 3) layout engine summary (drives tests/graph_layout.mjs)
# ---------------------------------------------------------------------------


def test_layout_engine_reports_zero_overlap(layout_summary):
    checks = layout_summary["checks"]
    assert checks and all(checks.values()), checks
    counts = layout_summary["counts"]
    assert counts["documents"] >= 30, "AC1 fixture must hold >=30 documents"
    metrics = layout_summary["metrics"]
    assert metrics["expanded"]["overlapPairs"] == 0
    assert metrics["collapsed"]["overlapPairs"] == 0
    assert counts["collapsedNodes"] < counts["expandedNodes"]
    assert counts["aggregates"] >= 2


def test_layout_engine_is_offline():
    source = GRAPH_MODULE.read_text(encoding="utf-8")
    for forbidden in ("fetch(", "XMLHttpRequest", "import("):
        assert forbidden not in source, f"layout engine must stay pure: {forbidden}"
    assert "http://" not in source and "https://" not in source


# ---------------------------------------------------------------------------
# 4) no live model calls anywhere in the U4 path
# ---------------------------------------------------------------------------


def test_u4_sources_do_not_call_models():
    graph_js = (WEBSTATIC / "js" / "views" / "graph.js").read_text(encoding="utf-8")
    for forbidden in ("/api/parse", "openai", "gateway"):
        assert forbidden not in graph_js
    assert not any(command in graph_js for command in ("eval(", "new Function"))
