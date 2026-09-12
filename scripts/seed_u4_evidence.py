"""Seed a temporary 43-document library for the U4 graph evidence capture.

Offline: uses the public FileDocumentStore API only (no model, no network).
Creates 43 documents with several topics/tags plus collections and manual
relations so all three edge sources and the cluster convergence mode appear.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph2note.store import FileDocumentStore  # noqa: E402

TITLES = [
    "线性代数讲义", "微积分复习提纲", "概率论习题", "复变函数笔记", "数值分析实验",
    "力学基础", "电磁学摘要", "热力学要点", "光学实验记录", "量子力学导论",
    "有机化学笔记", "无机化学整理", "分析化学实验", "物理化学公式", "高分子材料",
    "细胞生物学", "遗传学笔记", "生态学综述", "免疫学要点", "生物化学整理",
    "中国古代史", "近代史纲要", "世界史笔记", "考古发现记录", "史料整理方法",
    "唐诗鉴赏", "现代文学笔记", "比较文学导论", "写作训练札记", "文学理论选读",
    "机械设计基础", "电路分析笔记", "信号与系统", "控制系统实验", "材料力学",
    "素描技法", "色彩构成", "艺术史笔记", "设计方法论", "摄影构图",
    "随机过程简介", "最优化方法", "未归类的手稿页",
]
TOPICS = ["数学", "物理", "化学", "生物", "历史", "文学", "工程", "艺术"]
TAGS = ["重点", "草稿", "待整理", "复习", "参考", "归档", "疑问"]
COLLECTIONS = ["学期论文", "实验报告"]
MANUAL_RELATIONS = [(0, 1), (0, 2), (5, 6), (10, 11), (20, 26), (30, 31)]


def main(target: str) -> int:
    root = Path(target)
    if root.exists():
        shutil.rmtree(root)
    store = FileDocumentStore(root)
    collection_ids = {name: store.create_collection(name)["collection_id"] for name in COLLECTIONS}

    for index, title in enumerate(TITLES):
        document_id = f"doc-{index:02d}"
        store.save_document(
            document_id=document_id,
            title=title,
            source_job_id=f"seed-job-{index:02d}",
            model="fixture",
            markdown=f"# {title}\n\n种子文档，用于 U4 图谱验收截图。\n",
            ir_json=json.dumps({"blocks": []}),
            original_path="",
            original_ext=".jpg",
            preprocessed_path="",
            preprocessed_raw_path="",
            assets_dir="",
            timing_json={},
        )
        if index < len(TITLES) - 1:  # last document stays unclustered
            store.set_topics(document_id, [TOPICS[index % len(TOPICS)]])
            store.set_tags(document_id, [TAGS[index % len(TAGS)], TAGS[(index + 3) % len(TAGS)]])
        if index % 7 == 0:
            store.set_collections(document_id, [collection_ids[COLLECTIONS[0]]])
        if index % 11 == 3:
            store.set_collections(document_id, [collection_ids[COLLECTIONS[1]]])

    for source, target_index in MANUAL_RELATIONS:
        document_id = f"doc-{source:02d}"
        store.set_manual_relations(document_id, [{
            "from": document_id, "to": f"doc-{target_index:02d}", "kind": "manual",
        }])

    print(json.dumps({
        "storage": str(root),
        "documents": len(TITLES),
        "topics": len(TOPICS),
        "tags": len(TAGS),
        "collections": len(collection_ids),
        "manual_relations": len(MANUAL_RELATIONS),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/u4-storage"))
