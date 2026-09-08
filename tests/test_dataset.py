"""dataset 加载测试：验证 metadata 解析与类目校验（不触网）。"""

import pytest

from eval.dataset import CATEGORIES, load_dataset, read_gold


def test_dataset_loads_and_reads_gold():
    dataset = load_dataset()
    assert len(dataset) >= 2  # test-images 现有 2 张
    for s in dataset:
        assert s.category in CATEGORIES
        assert s.gold_path.endswith(".md")
        gold = read_gold(s)
        assert isinstance(gold, str) and len(gold) > 0
