"""Multi-turn Q&A session state for grounded PDF Q&A (P1).

The single-turn answerer (issue 11, :mod:`graph2note.pdfqa`) is extended with an
explicit conversation session.  This module owns **only** the session state:

- a :class:`Turn` per answered/failed question (question + answer + the page
  citations that were validated *for that turn*), and
- a :class:`QaSession` that binds a retrieval ``scope`` and keeps a bounded turn
  history, plus an aggregate telemetry record.

State is kept in memory and (when a root is configured) persisted as one JSON
file per session, so a restart can resume the conversation.  All bounds are
explicit:

``MAX_CONTEXT_TURNS``
    how many of the most recent turns are replayed into the prompt.  Older turns
    stay in the session record but never reach the model.
``MAX_SESSION_TURNS``
    how many turns are retained on disk per session (FIFO).
``MAX_SESSIONS``
    how many sessions are retained; the least-recently-updated is evicted.

Nothing here calls a model or the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# Explicit bounds (P1 AC4/AC5).
MAX_CONTEXT_TURNS = int(os.environ.get("GRAPH2NOTE_PDF_QA_CONTEXT_TURNS", "5"))
MAX_SESSION_TURNS = int(os.environ.get("GRAPH2NOTE_PDF_QA_MAX_SESSION_TURNS", "20"))
MAX_SESSIONS = int(os.environ.get("GRAPH2NOTE_PDF_QA_MAX_SESSIONS", "100"))
SESSION_ID_MAX_CHARS = 128
SESSION_DIRNAME = "qa-sessions"

# A session id is opaque client state: accept any non-empty, whitespace/slash
# free token up to the explicit cap.  The on-disk filename is a hash, so even a
# hostile id can never escape the session directory.
_SESSION_ID_RE = re.compile(r"^[^\s/\\\x00]{1,%d}$" % SESSION_ID_MAX_CHARS)


def is_valid_session_id(session_id: object) -> bool:
    return bool(_SESSION_ID_RE.match(str(session_id or "")))


class SessionError(ValueError):
    """Malformed session identifier or scope payload."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # invalid


def session_file(root: Path | str, session_id: str) -> Path:
    """Deterministic on-disk path for a session (hashed -> path-safe)."""
    digest = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:24]
    return Path(root) / f"{digest}.json"


def _as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass
class Turn:
    """One question/answer exchange and the citations validated for it."""

    index: int
    question: str
    answer: str = ""
    status: str = "answered"
    citations: list[dict] = field(default_factory=list)
    untrusted_citations: list[str] = field(default_factory=list)
    retrieved: int = 0
    model: str | None = None
    provider: str | None = None
    usage: dict = field(default_factory=dict)
    telemetry: dict = field(default_factory=dict)
    elapsed: float = 0.0
    created_at: float = 0.0

    def public(self) -> dict:
        return {
            "index": self.index,
            "question": self.question,
            "answer": self.answer,
            "status": self.status,
            "citations": self.citations,
            "untrusted_citations": self.untrusted_citations,
            "retrieved": self.retrieved,
            "model": self.model,
            "provider": self.provider,
            "usage": self.usage,
            "telemetry": self.telemetry,
            "elapsed": round(self.elapsed, 3),
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict:
        return self.public()

    @classmethod
    def from_dict(cls, data: dict) -> "Turn":
        data = data if isinstance(data, dict) else {}
        return cls(
            index=_as_int(data.get("index")),
            question=str(data.get("question") or ""),
            answer=str(data.get("answer") or ""),
            status=str(data.get("status") or "answered"),
            citations=list(data.get("citations") or []),
            untrusted_citations=list(data.get("untrusted_citations") or []),
            retrieved=_as_int(data.get("retrieved")),
            model=data.get("model"),
            provider=data.get("provider"),
            usage=dict(data.get("usage") or {}),
            telemetry=dict(data.get("telemetry") or {}),
            elapsed=float(data.get("elapsed") or 0.0),
            created_at=float(data.get("created_at") or 0.0),
        )


@dataclass
class QaSession:
    """Conversation state bound to one retrieval scope."""

    session_id: str
    pdf_ids: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def scope(self) -> dict:
        if not self.pdf_ids:
            return {"kind": "all", "pdf_ids": []}
        if len(self.pdf_ids) == 1:
            return {"kind": "pdf", "pdf_ids": list(self.pdf_ids)}
        return {"kind": "multi", "pdf_ids": list(self.pdf_ids)}

    def context_turns(self, limit: int = MAX_CONTEXT_TURNS) -> list[Turn]:
        """Most recent turns eligible for the prompt (oldest truncated first)."""
        limit = max(0, int(limit))
        return self.turns[-limit:] if limit else []

    def append(self, turn: Turn) -> None:
        self.turns.append(turn)
        if len(self.turns) > MAX_SESSION_TURNS:
            self.turns = self.turns[-MAX_SESSION_TURNS:]
        self.updated_at = time.time()

    def telemetry(self) -> dict:
        """Aggregate session telemetry (counts + token totals by turn)."""
        prompt = sum(_as_int((t.telemetry or {}).get("prompt_tokens")) for t in self.turns)
        completion = sum(_as_int((t.telemetry or {}).get("completion_tokens")) for t in self.turns)
        total = sum(_as_int((t.telemetry or {}).get("total_tokens")) for t in self.turns)
        model_calls = sum(1 for t in self.turns if t.telemetry and t.telemetry.get("has_usage"))
        failed_turns = sum(1 for t in self.turns if t.status != "answered")
        last = next((t for t in reversed(self.turns) if t.telemetry), None)
        return {
            "schema_version": 1,
            "session_id": self.session_id,
            "turns": len(self.turns),
            "model_calls": model_calls,
            "failed_turns": failed_turns,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "provider": (last.telemetry.get("provider") if last else None),
            "model": (last.telemetry.get("model") if last else None),
            "by_turn": [
                {
                    "index": t.index,
                    "status": t.status,
                    "prompt_tokens": (t.telemetry or {}).get("prompt_tokens"),
                    "completion_tokens": (t.telemetry or {}).get("completion_tokens"),
                    "total_tokens": (t.telemetry or {}).get("total_tokens"),
                }
                for t in self.turns
            ],
        }

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "scope": self.scope,
            "turn_count": len(self.turns),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "telemetry": self.telemetry(),
        }

    def public(self) -> dict:
        return {
            **self.summary(),
            "turns": [t.public() for t in self.turns],
            "limits": {
                "max_context_turns": MAX_CONTEXT_TURNS,
                "max_session_turns": MAX_SESSION_TURNS,
                "max_sessions": MAX_SESSIONS,
            },
        }

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "pdf_ids": list(self.pdf_ids),
            "turns": [t.to_dict() for t in self.turns],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QaSession":
        data = data if isinstance(data, dict) else {}
        session = cls(
            session_id=str(data.get("session_id") or ""),
            pdf_ids=[str(x) for x in (data.get("pdf_ids") or []) if str(x).strip()],
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
        )
        session.turns = [Turn.from_dict(t) for t in (data.get("turns") or [])]
        return session


class SessionStore:
    """In-memory session registry with optional JSON persistence.

    ``root=None`` keeps everything in memory (tests, ephemeral use); otherwise
    sessions are lazily loaded from ``root`` and written back on every save, so
    a process restart resumes the conversation.
    """

    def __init__(self, root: Path | str | None = None, *,
                 max_sessions: int = MAX_SESSIONS) -> None:
        self.root = Path(root) if root is not None else None
        self.max_sessions = max(1, int(max_sessions))
        self._sessions: dict[str, QaSession] = {}
        self._lock = threading.RLock()
        self._loaded = False

    # -- loading / capacity ---------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if self.root is not None and self.root.is_dir():
                for path in sorted(self.root.glob("*.json")):
                    session = self._read(path)
                    if session is not None:
                        self._sessions[session.session_id] = session
                self._evict_locked()
            self._loaded = True

    @staticmethod
    def _read(path: Path) -> QaSession | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        session = QaSession.from_dict(data)
        return session if session.session_id else None

    def _evict_locked(self, keep: str | None = None) -> None:
        while len(self._sessions) > self.max_sessions:
            candidates = [s for s in self._sessions.values() if s.session_id != keep]
            if not candidates:  # never evict the session we are persisting now
                return
            oldest = min(candidates, key=lambda s: s.updated_at or 0.0)
            self._sessions.pop(oldest.session_id, None)
            self._remove_file(oldest.session_id)

    def _remove_file(self, session_id: str) -> None:
        if self.root is None:
            return
        try:
            session_file(self.root, session_id).unlink(missing_ok=True)
        except OSError:
            pass

    # -- public API -----------------------------------------------------------
    def get(self, session_id: str) -> QaSession | None:
        self._ensure_loaded()
        with self._lock:
            return self._sessions.get(session_id)

    def get_or_create(self, session_id: str, pdf_ids: list[str] | None = None) -> QaSession:
        self._ensure_loaded()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                return session
            now = time.time()
            session = QaSession(
                session_id=session_id,
                pdf_ids=[str(x) for x in (pdf_ids or []) if str(x).strip()],
                created_at=now,
                updated_at=now,
            )
            self._sessions[session_id] = session
            self._evict_locked(keep=session_id)
            return session

    def save(self, session: QaSession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session
            self._evict_locked(keep=session.session_id)
            if self.root is None:
                return
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                path = session_file(self.root, session.session_id)
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(
                    json.dumps(session.to_dict(), ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                os.replace(tmp, path)
            except OSError:
                pass  # an unwritable cache must never break answering

    def list_sessions(self) -> list[dict]:
        self._ensure_loaded()
        with self._lock:
            sessions = sorted(
                self._sessions.values(),
                key=lambda s: (s.updated_at or 0.0, s.session_id),
                reverse=True,
            )
            return [s.summary() for s in sessions]

    def delete(self, session_id: str) -> bool:
        self._ensure_loaded()
        with self._lock:
            existed = self._sessions.pop(session_id, None) is not None
            self._remove_file(session_id)
            return existed

    def count(self) -> int:
        self._ensure_loaded()
        with self._lock:
            return len(self._sessions)


__all__ = [
    "SessionError",
    "Turn",
    "QaSession",
    "SessionStore",
    "is_valid_session_id",
    "session_file",
    "MAX_CONTEXT_TURNS",
    "MAX_SESSION_TURNS",
    "MAX_SESSIONS",
    "SESSION_ID_MAX_CHARS",
    "SESSION_DIRNAME",
]
