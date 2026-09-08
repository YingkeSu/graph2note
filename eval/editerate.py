"""字符级差异度量实现：Levenshtein 编辑距离 + EditRate。

定义（与 PRD/SPEC 对齐）：
- 编辑字符数 = 把 pred 变换为 gold 所需的最小字符级编辑操作数
  （插入/删除/替换各计 1 个编辑字符）。
- EditRate = 编辑字符数 / 总字符数，其中总字符数取 gold 的字符数。

空串边界：为避免除零，分母取 max(len(gold), 1)。
"""

from __future__ import annotations


class EditDistance:
    """一次字符级 diff 的结果。"""

    __slots__ = ("edits", "insertions", "deletions", "substitutions")

    def __init__(
        self,
        edits: int,
        insertions: int,
        deletions: int,
        substitutions: int,
    ) -> None:
        self.edits = edits
        self.insertions = insertions
        self.deletions = deletions
        self.substitutions = substitutions

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"EditDistance(edits={self.edits}, ins={self.insertions}, "
            f"del={self.deletions}, sub={self.substitutions})"
        )


def _content_units(text: str) -> str:
    """把文本归一化为用于 diff 的字符单位。

    这里按「用户实际要改的」口径：跳过输出质量与语义无关的空白压缩差异，
    但保留内容的字符级差异。当前保持原样（不做归一化），
    只把输入强制为 str，便于后续扩展（如剔除首尾空白）。
    """
    return text if isinstance(text, str) else str(text)


def compute_edit_distance(gold: str, pred: str) -> EditDistance:
    """计算 gold 与 pred 的 Levenshtein 编辑距离及插入/删除/替换分解。

    用完整 DP 表以便回溯统计各类操作数，适合中小文档（评估集规模内）。
    """
    a = _content_units(gold)
    b = _content_units(pred)
    m, n = len(a), len(b)

    # dp[i][j] = 把 a[:i] 变换为 b[:j] 的最小编辑数
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        ai = a[i - 1]
        for j in range(1, n + 1):
            if ai == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],      # 删除 a[i-1]
                    dp[i][j - 1],      # 插入 b[j-1]
                    dp[i - 1][j - 1],  # 替换 a[i-1] -> b[j-1]
                )

    # 回溯统计操作类型
    insertions = deletions = substitutions = 0
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and a[i - 1] == b[j - 1]:
            i, j = i - 1, j - 1
        else:
            cand = [
                (dp[i - 1][j - 1] if i > 0 and j > 0 else float("inf"), "sub"),
                (dp[i - 1][j] if i > 0 else float("inf"), "del"),
                (dp[i][j - 1] if j > 0 else float("inf"), "ins"),
            ]
            best = min(cand, key=lambda x: x[0])
            op = best[1]
            if op == "sub":
                substitutions += 1
                i, j = i - 1, j - 1
            elif op == "del":
                deletions += 1
                i -= 1
            else:
                insertions += 1
                j -= 1

    return EditDistance(dp[m][n], insertions, deletions, substitutions)


def edit_rate(gold: str, pred: str) -> float:
    """EditRate = 编辑字符数 / max(len(gold), 1)。"""
    a = _content_units(gold)
    dist = compute_edit_distance(a, pred)
    denominator = max(len(a), 1)
    return dist.edits / denominator
