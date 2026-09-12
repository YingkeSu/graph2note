"""Minimal stdlib HTML DOM tree for structural assertions (U3).

Small enough to parse ``index.html`` into an element tree without a browser or
third-party dependency.  Extracted so layout tests in different modules share
one parser instead of copy-pasting it.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

VOID_TAGS = {
    "meta", "link", "img", "input", "br", "hr", "source", "area", "base",
    "col", "embed", "param", "track", "wbr",
}


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


def load_dom(path: str | Path) -> Element:
    parser = _DomParser()
    parser.feed(Path(path).read_text(encoding="utf-8"))
    return parser.root
