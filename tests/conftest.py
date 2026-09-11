"""pytest 自动分类标记（issue 12）。

收集期按测试文件名打模块/层次/成本 marker，**不修改任何测试文件内容**，避免与
在途分支（07/08/black-fix）的测试文件冲突。分类数据在 ``tests/taxonomy.py``。

模块级运行：``pytest -m webapp``；一键封装见 ``scripts/run_tests.sh``。
"""

from __future__ import annotations

from pathlib import Path

from tests.taxonomy import FILE_TO_MODULE, INTEGRATION_FILES, SLOW_FILES


def pytest_collection_modifyitems(config, items):
    for item in items:
        stem = Path(item.location[0]).stem
        module = FILE_TO_MODULE.get(stem)
        if module is not None:
            item.add_marker(module)
        item.add_marker("integration" if stem in INTEGRATION_FILES else "unit")
        if stem in SLOW_FILES:
            item.add_marker("slow")
