"""评估集加载：fixtures 目录约定 + metadata.json 清单。

目录约定（见 eval/fixtures/CATEGORIES.md）：
- 图片按类目存放，样本唯一 id 标识。
- 每样本一条 metadata 记录：id、category、image（相对仓库根路径）、
  gold（相对仓库根路径的 gold markdown）、gold_proofed（人工校对标记）、notes。
- gold 未人工校对时 gold_proofed=False，报告必须标注「未经人工校对」。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# 六类目（与 PRD/SPEC 对齐）
CATEGORIES: dict[str, str] = {
    "handwriting": "手写笔记",
    "print": "印刷扫描",
    "formula": "数学公式",
    "mixed": "中英混排",
    "flowchart": "流程图/架构图",
    "strikethrough": "涂改/删除线",
}

CATEGORY_ORDER = ["handwriting", "print", "formula", "mixed", "flowchart", "strikethrough"]

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
FIXTURES_DIR = os.path.join(HERE, "fixtures")
DATA_DIR = os.path.join(FIXTURES_DIR, "data")
GOLD_DIR = os.path.join(FIXTURES_DIR, "gold")
METADATA_PATH = os.path.join(FIXTURES_DIR, "metadata.json")


@dataclass
class Sample:
    id: str
    category: str
    image: str
    gold: str
    gold_proofed: bool = False
    language: str = "zh"
    notes: str = ""
    deletion_note: str = ""  # 涂改类目专用：语义化删除表现记录

    @property
    def image_path(self) -> str:
        p = self.image
        return p if os.path.isabs(p) else os.path.join(REPO_ROOT, p)

    @property
    def gold_path(self) -> str:
        p = self.gold
        return p if os.path.isabs(p) else os.path.join(REPO_ROOT, p)


def load_metadata() -> list[dict]:
    if not os.path.exists(METADATA_PATH):
        return []
    with open(METADATA_PATH, encoding="utf-8") as fh:
        return json.load(fh).get("samples", [])


def load_dataset() -> list[Sample]:
    samples = []
    for entry in load_metadata():
        category = entry.get("category", "")
        if category not in CATEGORIES:
            raise ValueError(f"未知类目 {category!r}（样本 {entry.get('id')}）")
        samples.append(
            Sample(
                id=entry["id"],
                category=category,
                image=entry["image"],
                gold=entry.get("gold", ""),
                gold_proofed=bool(entry.get("gold_proofed", False)),
                language=entry.get("language", "zh"),
                notes=entry.get("notes", ""),
                deletion_note=entry.get("deletion_note", ""),
            )
        )
    return samples


def read_gold(sample: Sample) -> str:
    with open(sample.gold_path, encoding="utf-8") as fh:
        return fh.read()
