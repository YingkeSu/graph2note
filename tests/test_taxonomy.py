"""测试分类自身的元测试（issue 12）：覆盖完整 + marker 已注册。

这两个断言保证：新增测试文件必须登记模块归属；conftest 打出的 marker 名都必须
在 pyproject.toml 注册（否则 --strict-markers 会报 unknown marker）。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from tests.taxonomy import FILE_TO_MODULE, INTEGRATION_FILES, MODULE_NAMES, SLOW_FILES

TESTS_DIR = Path(__file__).parent
ROOT = TESTS_DIR.parent


def test_every_test_file_has_module_mapping():
    files = {p.stem for p in TESTS_DIR.glob("test_*.py")}
    unmapped = sorted(files - set(FILE_TO_MODULE))
    assert not unmapped, (
        f"未登记模块归属的测试文件（请在 tests/taxonomy.py 的 FILE_TO_MODULE 补登）: {unmapped}"
    )


def test_all_markers_used_are_registered_in_pyproject():
    raw = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    registered = raw["tool"]["pytest"]["ini_options"]["markers"]
    registered_names = {m.split(":", 1)[0].strip() for m in registered}

    used = set(MODULE_NAMES) | {"unit", "integration", "slow"}
    missing = sorted(used - registered_names)
    assert not missing, f"conftest 使用但未在 pyproject 注册的 marker: {missing}"


def test_integration_and_slow_sets_only_contain_mapped_files():
    mapped = set(FILE_TO_MODULE)
    assert set(INTEGRATION_FILES) <= mapped
    assert set(SLOW_FILES) <= mapped
