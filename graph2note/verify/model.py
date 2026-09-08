"""Cross-validation report data model (issue 10)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# Three divergence classes (SPEC FR-024 / 分歧报告实体):
CONSISTENT = "consistent"   # 双侧一致 —— 高置信
ONE_SIDE = "one_side"       # 单侧出现 —— 疑似漏识别
CONFLICT = "conflict"       # 不一致  —— 内容冲突，需用户审核


@dataclass
class DiffBlock:
    """One block-level note in the divergence report (aggregated by block)."""

    tag: str                                      # CONSISTENT / ONE_SIDE / CONFLICT
    block_type: str
    text_a: Optional[str] = None                  # normalized text from doc A
    text_b: Optional[str] = None                  # normalized text from doc B
    index_a: Optional[int] = None                 # 0-based position in doc A
    index_b: Optional[int] = None                 # 0-based position in doc B
    similarity: Optional[float] = None
    side: str = "a"                               # which doc is present: a | b | both
    block: object = None                          # original block (not serialized)


@dataclass
class BlockDiff:
    """Aggregated block-level diff of two Document IRs."""

    consistent: list = field(default_factory=list)   # list[DiffBlock]
    one_side: list = field(default_factory=list)     # list[DiffBlock]
    conflict: list = field(default_factory=list)     # list[DiffBlock]
    order_changed: bool = False
    note: str = ""

    @property
    def counts(self) -> dict:
        return {
            CONSISTENT: len(self.consistent),
            ONE_SIDE: len(self.one_side),
            CONFLICT: len(self.conflict),
        }

    def summary(self) -> dict:
        return {
            "counts": self.counts,
            "order_changed": self.order_changed,
            "note": self.note,
            "consistent": [_public(d) for d in self.consistent],
            "one_side": [_public(d) for d in self.one_side],
            "conflict": [_public(d) for d in self.conflict],
        }


@dataclass
class DuplicateGroup:
    """A set of near-duplicate blocks *within* one document IR."""

    group_id: int
    indexes: list                     # 0-based block indices that are near-dups
    block_type: str
    similarity: float                 # min pair similarity inside the group
    representative_text: str = ""

    def summary(self) -> dict:
        return asdict(self)


@dataclass
class CrossValidationReport:
    """End product of ``verify``: diff + within-doc dups + model status."""

    source: str
    model_a: str
    model_b: str
    diff: BlockDiff = field(default_factory=BlockDiff)
    duplicates_a: list = field(default_factory=list)   # list[DuplicateGroup]
    duplicates_b: list = field(default_factory=list)
    verified: bool = True              # False => degraded to single model
    note: str = ""                     # "未验证..." when not verified
    meta_a: dict = field(default_factory=dict)
    meta_b: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "model_a": self.model_a,
            "model_b": self.model_b,
            "verified": self.verified,
            "note": self.note,
            "diff": self.diff.summary(),
            "duplicates_a": [d.summary() for d in self.duplicates_a],
            "duplicates_b": [d.summary() for d in self.duplicates_b],
            "meta_a": self.meta_a,
            "meta_b": self.meta_b,
            "warnings": self.warnings,
        }


def _public(d: DiffBlock) -> dict:
    """Serializable public shape of a DiffBlock (no raw block, no None noise)."""
    return {
        "tag": d.tag,
        "block_type": d.block_type,
        "text_a": d.text_a,
        "text_b": d.text_b,
        "index_a": d.index_a,
        "index_b": d.index_b,
        "similarity": d.similarity,
        "side": d.side,
    }


__all__ = [
    "CONSISTENT", "ONE_SIDE", "CONFLICT",
    "DiffBlock", "BlockDiff", "DuplicateGroup", "CrossValidationReport",
]