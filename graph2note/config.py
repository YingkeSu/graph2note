"""Shared runtime configuration — unified document-library resolution (issue 02).

Web, CLI and the macOS desktop all resolve the document library and the LLM
settings file through the *same* explicit priority:

    storage  : explicit arg > GRAPH2NOTE_STORAGE > <support>/storage
    settings : GRAPH2NOTE_SETTINGS_FILE > <storage>/llm-settings.json
    support  : GRAPH2NOTE_APP_SUPPORT > ~/Library/Application Support/Graph2Note

No entry point hardcodes a different fallback.  Existing data in the legacy
defaults (``./.g2n-storage``, ``./storage``) is never moved, overwritten or
hidden — set ``GRAPH2NOTE_STORAGE`` (or pass ``--storage``) to keep using it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Graph2Note"


class ConfigError(ValueError):
    """Raised when runtime configuration is invalid (unwritable path, etc.)."""


def support_dir() -> Path:
    """Per-user application support root (settings + data)."""
    configured = os.environ.get("GRAPH2NOTE_APP_SUPPORT", "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


def resolve_storage_dir(explicit: str | os.PathLike | None = None) -> Path:
    """Resolve the document library directory.

    Priority: explicit argument > ``GRAPH2NOTE_STORAGE`` env > ``<support>/storage``.
    """
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser()
    env = os.environ.get("GRAPH2NOTE_STORAGE", "").strip()
    if env:
        return Path(env).expanduser()
    return support_dir() / "storage"


def resolve_settings_file(storage_dir: str | os.PathLike) -> Path:
    """Resolve the LLM settings file for a given storage dir.

    Priority: ``GRAPH2NOTE_SETTINGS_FILE`` env > ``<storage>/llm-settings.json``.
    """
    env = os.environ.get("GRAPH2NOTE_SETTINGS_FILE", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(storage_dir) / "llm-settings.json"


def ensure_storage_dir(path: str | os.PathLike) -> Path:
    """Create ``path`` as a directory, with a locatable error on failure.

    Rejects a path that already exists as a non-directory, and surfaces an
    ``ConfigError`` (not a bare ``OSError``) when the path cannot be created.
    """
    path = Path(path).expanduser()
    if path.exists() and not path.is_dir():
        raise ConfigError(f"storage path is not a directory: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"storage path is not writable: {path} ({exc})") from exc
    return path


def describe(storage: str | os.PathLike | None = None) -> dict:
    """Human/machine readable view of the effective runtime config."""
    support = support_dir()
    storage_path = resolve_storage_dir(storage)
    settings_path = resolve_settings_file(storage_path)
    return {
        "support": str(support),
        "storage": str(storage_path),
        "settings": str(settings_path),
    }


__all__ = [
    "APP_NAME",
    "ConfigError",
    "support_dir",
    "resolve_storage_dir",
    "resolve_settings_file",
    "ensure_storage_dir",
    "describe",
]
