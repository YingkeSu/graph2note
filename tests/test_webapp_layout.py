"""U1 layout + navigation contracts (offline).

Two complementary checks:

1. DOM assertions over ``index.html`` parsed into a tiny element tree: the
   three-zone shell (sidebar / topbar / content), the sidebar nav set, the
   <=4 topbar controls and the fact that Library no longer hosts the moved
   blocks (collection tree / tag vocabulary / PDF search+Q&A).
2. Route contract: ``node tests/router_routes.mjs`` exercises the pure hash
   parser + view dispatch (skipped when node is unavailable).

No network: the static-serving check uses the local FastAPI TestClient.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from graph2note import webapp
from tests.static_assets import WEBSTATIC, static_js  # noqa: F401

TESTS_DIR = Path(__file__).parent
VOID_TAGS = {
    "meta", "link", "img", "input", "br", "hr", "source", "area", "base",
    "col", "embed", "param", "track", "wbr",
}


# ---------------------------------------------------------------------------
# tiny DOM parser (stdlib only) — enough for structural assertions
# ---------------------------------------------------------------------------


class Element:
    def __init__(self, tag: str, attrs: dict, parent: "Element | None" = None):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Element] = []

    @property
    def id(self) -> str | None:
        return self.attrs.get("id")

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def iter_elements(self):
        for child in self.children:
            yield child
            yield from child.iter_elements()

    def find(self, *, id: str | None = None, tag: str | None = None,
             cls: str | None = None) -> "Element | None":
        for node in self.iter_elements():
            if id is not None and node.id != id:
                continue
            if tag is not None and node.tag != tag:
                continue
            if cls is not None and cls not in node.classes:
                continue
            return node
        return None

    def find_all(self, *, tag: str | None = None, cls: str | None = None) -> list["Element"]:
        return [
            node for node in self.iter_elements()
            if (tag is None or node.tag == tag) and (cls is None or cls in node.classes)
        ]

    def contains_id(self, target: str) -> bool:
        return any(node.id == target for node in self.iter_elements())


class _DomParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Element(tag, dict(attrs), self.stack[-1]))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return


@pytest.fixture(scope="module")
def dom() -> Element:
    parser = _DomParser()
    parser.feed((WEBSTATIC / "index.html").read_text(encoding="utf-8"))
    return parser.root


# ---------------------------------------------------------------------------
# 1) shell / layout DOM assertions
# ---------------------------------------------------------------------------


def test_three_zone_shell_present(dom):
    shell = dom.find(id="app-shell")
    assert shell is not None
    sidebar = shell.find(id="app-sidebar")
    main = shell.find(cls="main")
    assert sidebar is not None and main is not None
    topbar = main.find(tag="header", cls="topbar")
    content = main.find(id="content")
    assert topbar is not None and content is not None
    # every routable zone lives in the content area, not in the sidebar/topbar
    for zone in ("library-zone", "timeline-zone", "graph-zone", "dashboard-zone",
                 "inbox-zone", "settings-zone", "vault-export-zone", "tags-zone",
                 "pdf-search-zone", "upload-zone", "work-zone"):
        assert content.find(id=zone) is not None, zone


def test_sidebar_owns_view_nav_and_collection_tree(dom):
    sidebar = dom.find(id="app-sidebar")
    nav_ids = {node.id for node in sidebar.find_all(cls="nav-item")}
    assert {
        "nav-library", "nav-timeline", "nav-graph", "nav-dashboard", "nav-inbox",
    } <= nav_ids, "all five view nav items must live in the sidebar"
    assert {"nav-settings", "nav-vault-export"} <= nav_ids, "secondary entries"
    assert sidebar.find(id="collection-tree") is not None
    assert sidebar.find(id="collection-create-form") is not None
    # the tag vocabulary is a view, not a nav sidebar block
    assert sidebar.find(id="tag-list") is None


def test_topbar_has_at_most_four_controls(dom):
    topbar = dom.find(tag="header", cls="topbar")
    controls = [n for n in topbar.iter_elements()
                if n.tag in {"a", "button", "input", "select"}]
    assert len(controls) == 4, [n.id or n.tag for n in controls]
    ids = {n.id for n in controls}
    assert {"sidebar-toggle", "global-search-input", "nav-upload"} <= ids
    # brand link (no id) is the fourth control
    assert len([n for n in controls if "brand" in n.classes]) == 1
    # none of the view nav buttons may sit in the topbar
    for nav_id in ("nav-library", "nav-timeline", "nav-graph", "nav-dashboard",
                   "nav-inbox", "nav-settings", "nav-vault-export"):
        assert topbar.find(id=nav_id) is None, nav_id


def test_library_is_grid_first_without_moved_blocks(dom):
    library = dom.find(id="library-zone")
    assert library.find(id="library-grid") is not None
    assert library.find(id="library-empty") is not None
    for moved in ("pdf-search", "pdf-search-results", "pdf-qa-form", "collection-tree",
                  "collection-create-form", "tag-vocabulary", "tag-list",
                  "workspace-navigation"):
        assert not library.contains_id(moved), f"{moved} must be moved out of Library"
    # the moved blocks are still reachable elsewhere
    assert dom.find(id="pdf-search-zone").contains_id("pdf-search")
    assert dom.find(id="pdf-search-zone").contains_id("pdf-search-results")
    assert dom.find(id="pdf-search-zone").contains_id("pdf-qa-form")
    assert dom.find(id="tags-zone").contains_id("tag-list")
    assert dom.find(id="tags-zone").contains_id("tag-create-form")


def test_entry_is_one_es_module_and_split_is_reachable(dom):
    scripts = [n for n in dom.iter_elements() if n.tag == "script"]
    module_scripts = [n for n in scripts if n.attrs.get("type") == "module"]
    assert [n.attrs.get("src") for n in module_scripts] == ["/static/app.js"]
    classic = [n for n in scripts if n.attrs.get("type") != "module" and n.attrs.get("src")]
    assert all(n.attrs["src"] != "/static/app.js" for n in classic), \
        "app.js must be loaded only as a module (zero-build)"

    js_modules = sorted((WEBSTATIC / "js").rglob("*.js"))
    assert len(js_modules) >= 5, f"expected >=5 ES modules, got {len(js_modules)}"
    reachable = _reachable_modules(WEBSTATIC / "app.js")
    for module in js_modules:
        assert module.resolve() in reachable, f"{module} is not imported from app.js"


_IMPORT_RE = re.compile(
    r"""(?:import|export)\s+(?:[^"']*?\s+from\s+)?["']([^"']+)["']"""
    r"""|import\s*\(\s*["']([^"']+)["']\s*\)"""
)


def _reachable_modules(entry: Path) -> set[Path]:
    seen: set[Path] = set()
    queue = [entry]
    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for match in _IMPORT_RE.finditer(path.read_text(encoding="utf-8")):
            spec = match.group(1) or match.group(2)
            if not spec or not spec.startswith("."):
                continue
            queue.append((path.parent / spec).resolve())
    return seen


# ---------------------------------------------------------------------------
# 2) route contract (pure functions, via node)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_router_hash_contract():
    proc = subprocess.run(
        ["node", str(TESTS_DIR / "router_routes.mjs")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


# ---------------------------------------------------------------------------
# 3) the split frontend is still served statically (zero-build)
# ---------------------------------------------------------------------------


def test_static_modules_are_served(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(webapp.create_app(storage_dir=tmp_path))
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    for module in sorted(WEBSTATIC.rglob("*.js")):
        rel = module.relative_to(WEBSTATIC).as_posix()
        response = client.get(f"/static/{rel}")
        assert response.status_code == 200, rel
