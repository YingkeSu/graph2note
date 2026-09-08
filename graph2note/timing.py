"""Staged timing recorder — baseline feeder for issue 11 (parse speed-up).

The pipeline records wall time per named stage (``preprocess``, ``llm``,
``render``, plus finer sub-stages) and writes a JSON timing file.  Issue 11
(``P95 <= 60s``) consumes this file as its baseline.  Deliberately simple and
deterministic: only stage names + monotonic seconds + total.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Iterator


class StageTimer:
    """Record elapsed seconds per named stage in insertion order."""

    def __init__(self) -> None:
        self._stages: list[dict] = []
        self._start_map: dict[str, float] = {}

    @contextlib.contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time a named stage; nested/duplicate names are allowed."""
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            self._stages.append({"name": name, "seconds": round(elapsed, 4)})

    @contextlib.contextmanager
    def span(self, name: str) -> Iterator[None]:
        """Alias kept for readability at the top-level pipeline phases."""
        with self.stage(name):
            yield

    def update(self, name: str, seconds: float) -> None:
        """Manually record a stage (e.g. already-timed by a sub-caller)."""
        self._stages.append({"name": name, "seconds": round(float(seconds), 4)})

    def to_dict(self) -> dict:
        stages = list(self._stages)
        total = round(sum(float(s["seconds"]) for s in stages), 4)
        return {
            "stages": stages,
            "stage_names": [s["name"] for s in stages],
            "total_seconds": total,
        }

    def as_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def write(self, path: str | None) -> str:
        """Write the JSON timing file; returns the JSON body regardless."""
        body = self.as_json()
        if path:
            import os

            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body + "\n")
        return body


class NullTimer(StageTimer):
    """Timer that records nothing (used when timing is disabled)."""

    def stage(self, name: str):  # type: ignore[override]
        class _null:
            def __enter__(self):  # noqa: N802
                return None

            def __exit__(self, *exc):  # noqa: N802
                return False

        return _null()

    def to_dict(self) -> dict:
        return {"stages": [], "stage_names": [], "total_seconds": 0.0}


__all__ = ["StageTimer", "NullTimer"]