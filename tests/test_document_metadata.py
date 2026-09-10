"""Offline contracts for Knowledge Workspace issue 01."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from graph2note.metadata import (
    extract_capture_time,
    infer_document_time,
    select_effective_time,
    validate_date_inference,
)
from graph2note.store import FileDocumentStore
from graph2note.webapp import create_app


def _exif_image(path: Path, value: str = "2024:02:29 09:08:07") -> Path:
    image = Image.new("RGB", (40, 40), "white")
    exif = Image.Exif()
    exif[36867] = value
    image.save(path, format="PNG", exif=exif.tobytes())
    return path


def _seed(store: FileDocumentStore, original: Path, markdown: str) -> str:
    assets = store.root / "seed-assets" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    store.save_document(
        document_id="doc-time",
        title="Time note",
        source_job_id="job-time",
        model="fixture",
        markdown=markdown,
        ir_json=json.dumps({"blocks": []}),
        original_path=str(original),
        original_ext=original.suffix,
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir=str(assets.parent),
        timing_json={},
        metadata={
            "capture_time": extract_capture_time(original),
            "document_time": infer_document_time(markdown),
        },
    )
    return "doc-time"


def test_exif_capture_time_is_normalized_and_missing_exif_is_safe(tmp_path):
    with_exif = extract_capture_time(_exif_image(tmp_path / "with.png"))
    assert with_exif == {
        "value": "2024-02-29T09:08:07",
        "source": "exif",
        "confidence": "high",
        "evidence": "DateTimeOriginal",
        "manual": False,
    }
    without_exif = extract_capture_time(tmp_path / "missing.png")
    assert without_exif["value"] is None
    assert without_exif["source"] == "none"


def test_date_inference_is_schema_validated_and_exposes_evidence():
    inferred = infer_document_time(
        "---\ndate: 2023-12-31\n---\n\n# 年终复盘\n"
    )
    assert inferred is not None
    assert inferred["value"] == "2023-12-31"
    assert inferred["confidence"] == "high"
    assert "date: 2023-12-31" in inferred["evidence"]
    assert validate_date_inference({
        "date": "2023-02-30", "confidence": "high", "evidence": "bad"
    }) is None
    assert validate_date_inference({
        "date": "2023-12-31", "confidence": "unknown", "evidence": "bad"
    }) is None


def test_effective_time_uses_document_then_capture_then_import():
    base = {
        "document_time": {"value": "2024-03-02", "source": "inferred"},
        "capture_time": {"value": "2024-03-01T10:00:00", "source": "exif"},
        "import_time": {"value": "2024-03-03T10:00:00", "source": "system"},
    }
    assert select_effective_time(base)["field"] == "document_time"
    base["document_time"] = {"value": None, "source": "none"}
    assert select_effective_time(base)["field"] == "capture_time"
    base["capture_time"] = {"value": None, "source": "none"}
    assert select_effective_time(base)["field"] == "import_time"


def test_metadata_persists_across_reload_and_manual_date_wins_reparse(tmp_path):
    root = tmp_path / "storage"
    original = _exif_image(tmp_path / "source.png")
    store = FileDocumentStore(root)
    did = _seed(store, original, "# Note\n\nDate: 2024-03-01\n")

    first = store.get_document(did)
    assert first["metadata"]["capture_time"]["value"] == "2024-02-29T09:08:07"
    assert first["metadata"]["document_time"]["value"] == "2024-03-01"
    assert first["metadata"]["import_time"]["value"]
    assert first["metadata"]["modified_time"]["value"]

    store.update_metadata(did, {"document_time": "2020-01-02"})
    reloaded = FileDocumentStore(root).get_document(did)
    assert reloaded["metadata"]["document_time"]["source"] == "manual"
    assert reloaded["metadata"]["document_time"]["value"] == "2020-01-02"
    assert reloaded["effective_time"]["value"] == "2020-01-02"

    # A later parse with a different inferred date cannot overwrite the manual
    # correction, while the content version still appends normally.
    store2 = FileDocumentStore(root)
    store2.save_document(
        document_id=did,
        title="Time note",
        source_job_id="job-time-2",
        model="fixture-2",
        markdown="# Note\n\nDate: 2025-04-05\n",
        ir_json=json.dumps({"blocks": []}),
        original_path=str(original),
        original_ext=".png",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir=str(root / "seed-assets"),
        timing_json={},
        metadata={"document_time": infer_document_time("Date: 2025-04-05")},
    )
    final = FileDocumentStore(root).get_document(did)
    assert len(final["versions"]) == 2
    assert final["metadata"]["document_time"]["value"] == "2020-01-02"


def test_metadata_api_reads_and_writes_contract(tmp_path):
    root = tmp_path / "storage"
    original = _exif_image(tmp_path / "source.png")
    store = FileDocumentStore(root)
    did = _seed(store, original, "# Note\n\n2024-03-01\n")
    client = TestClient(create_app(storage_dir=root, document_store=store))

    detail = client.get(f"/api/documents/{did}")
    assert detail.status_code == 200
    assert set(detail.json()["metadata"]) >= {
        "capture_time", "document_time", "import_time", "modified_time", "effective_time"
    }
    response = client.put(
        f"/api/documents/{did}/metadata",
        json={"document_time": "2021-06-07"},
    )
    assert response.status_code == 200
    assert response.json()["effective_time"]["value"] == "2021-06-07"
    assert client.get(f"/api/documents/{did}").json()["document_time"] == "2021-06-07"

    bad = client.put(
        f"/api/documents/{did}/metadata",
        json={"document_time": "2021-02-30"},
    )
    assert bad.status_code == 422
