"""EditRate 单元测试：构造已知 diff 的 gold/pred 对，断言折算正确。不触网。"""

import pytest

from eval.editerate import compute_edit_distance, edit_rate


def test_identical():
    ed = compute_edit_distance("hello 世界", "hello 世界")
    assert ed.edits == 0
    assert ed.insertions == ed.deletions == ed.substitutions == 0
    assert edit_rate("hello 世界", "hello 世界") == 0.0


def test_one_substitution():
    # SAC -> SAO 只差一个替换
    ed = compute_edit_distance("SAC", "SAO")
    assert ed.edits == 1
    assert ed.substitutions == 1
    assert ed.insertions == 0 and ed.deletions == 0
    assert edit_rate("SAC", "SAO") == 1 / 3


def test_full_deletion():
    ed = compute_edit_distance("hello world", "hello")
    assert ed.deletions == 6
    assert ed.edits == 6
    assert edit_rate("hello world", "hello") == 6 / 11


def test_full_insertion():
    ed = compute_edit_distance("hello", "hello world")
    assert ed.insertions == 6
    assert ed.edits == 6
    assert edit_rate("hello", "hello world") == 6 / 5  # 分母取 gold 长度


def test_substitution_vs_ins_del_mix():
    # abcd -> axd : a 同; b->x 替换; c 删除 = 2 编辑
    ed = compute_edit_distance("abcd", "axd")
    assert ed.edits == 2
    # 归一化
    assert edit_rate("abcd", "axd") == pytest.approx(2 / 4)


def test_empty_gold_guard():
    assert edit_rate("", "abc") == 3 / 1
    assert edit_rate("", "") == 0.0


def test_line_breaks_and_cjk():
    gold = "# 标题\n\n- 第一\n- 第二\n"
    pred = "# 标题\n\n- 第一\n- 第三\n"
    ed = compute_edit_distance(gold, pred)
    assert ed.edits == 1  # 「二」->「三」单字替换
    assert ed.substitutions == 1


def test_markdown_structure_drift():
    # 换了标题层级：标题加一个 #，属于一个替换
    ed = compute_edit_distance("# 主题", "## 主题")
    assert ed.edits == 1
