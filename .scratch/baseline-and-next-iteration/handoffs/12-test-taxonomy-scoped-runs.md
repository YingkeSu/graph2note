# Handoff 12 — 测试整理分类与模块级测试运行

> 来源：`issues/12-test-taxonomy-scoped-runs.md`（Status: in-review）。
> 消费者：dispatcher 验收、后续所有 worker（单模块开发只跑相关测试）、reviewer。
> 分支：`ao/graph2note-13/root`，实现提交 `987fb26`（基于 32fe1d3）。

## 1. 完成了什么

把「单模块开发只跑相关测试、大版本合并前才全量」制度化：

- **`pyproject.toml`**：`[tool.pytest.ini_options]` 注册 16 个模块 marker + `unit/integration`
  + `slow/live_llm/gui`，`addopts` 加 `--strict-markers`（未知 marker 直接报错）。
- **`tests/taxonomy.py` + `tests/conftest.py`**：收集期 `pytest_collection_modifyitems`
  按测试文件名自动打标（模块/层次/成本），**不修改任何测试文件内容**，避免与在途分支
  （07 的 test_webapp_vault_export、08 的 test_pdf_upload、black-fix 的 test_preprocess）冲突。
- **`tests/test_taxonomy.py`**（3 个元测试）：① 每个 `tests/test_*.py` 都有模块归属登记；
  ② conftest 用到的 marker 名都在 pyproject 注册（防 strict-markers 破裂）；③ 层次/成本集合
  只引用已登记文件。
- **`scripts/run_tests.sh`**：`<module...>`（多模块 or 组合）/ `--unit` / `--integration` /
  `--fast`（排除 slow）/ `--all`。
- **`docs/testing.md`**：三个维度说明 + 模块→测试文件映射表 + 「改了模块 X 应跑哪些测试」
  （含契约改动建议连同的邻近模块）+ 新增测试文件登记指引。
- **`docs/setup.md`**、**`docs/agents/parallel-dev.md` §6**：更新为新测试政策
  （单模块交付=模块范围+邻近；大版本/发布合并前=全量）。

## 2. 如何运行测试

```bash
# 全量（大版本合并前）
OPENCODE_API_KEY=dummy uv run pytest        # 425 passed, 2 skipped
# 模块级（单模块开发）
scripts/run_tests.sh webapp                 # 只跑 webapp 模块
scripts/run_tests.sh webapp notes           # 多模块
scripts/run_tests.sh --unit / --integration / --fast / --all
# 元测试
uv run pytest tests/test_taxonomy.py        # 3 passed
```

## 3. 决策与对 spec 的偏离

- **收集期自动打标（conftest）而非逐文件加 `pytestmark`**：唯一能在「不修改任何测试文件内容」
  前提下完成分类的方案，天然规避在途分支冲突；映射表集中在 `tests/taxonomy.py` 单点维护。
- **`live-llm` 用下划线**（指令草案写作 `live-llm`）：避免 `-m live-llm` 被解析成 `live - llm`
  表达式歧义；语义一致，已在 docs/testing.md 注明。本套件无 live/GUI 测试，这两个 marker 仅注册
  供手动/未来使用（0 用例）。
- **新增 `meta` 模块**：`test_taxonomy.py` 是测试基础设施自身，归 `meta` 而非硬塞进某产品模块。
- **全量数量 422→425 的说明**：既有 46 个测试文件的 collect 数量与分类前 `diff` 为空（逐项一致），
  +3 为本 issue 的元测试本身，非既有测试行为变化。

## 4. AC 证据对照

- AC1 每文件有模块 marker + strict-markers 无未注册：`tests/test_taxonomy.py` 三个元测试 +
  `OPENCODE_API_KEY=dummy uv run pytest`（425 passed / 2 skipped，无 unknown-marker 告警）。
- AC2 映射表入库 + 一键执行：`docs/testing.md` 映射表；`scripts/run_tests.sh webapp`（实测 4 文件）
  、`scripts/run_tests.sh meta`（3 passed）、`--fast`（51 慢测被排除）均可用。
- AC3 全量行为不变：分类前后 `--collect-only -q` 的 46 个既有文件数量 diff 为空（证据：
  `/tmp/g2n-baseline-files.txt` vs after 的 diff 结果，见本 handoff §5 备注）。
- AC4 docs 更新：`docs/agents/parallel-dev.md` §6、`docs/setup.md` 已改；新增 `docs/testing.md`。
- AC5 不碰在途文件：`git diff --name-only -- tests/test_webapp_vault_export.py tests/test_preprocess.py`
  为空；`test_pdf_upload.py`（08 在途）不存在于本 worktree，仅在映射表预登记，未创建/修改。

## 5. 未尽事项 / 在途分支合并后处理

1. **08 的 `tests/test_pdf_upload.py`**：已预登记为 `ingest` 模块；08 合并后无需改动即自动打标。
   若 08 新文件命名不同，需在 `tests/taxonomy.py` 补登（`test_taxonomy.py` 会拦下）。
2. **07 修改 `test_webapp_vault_export.py` / black-fix 修改 `test_preprocess.py`**：两者内容改动
   不影响标记（标记由文件名决定），合并后自动继承 `webapp`/`preprocess` marker，无需处理。
3. **既有「dummy key」前置问题**：全量测试需 `OPENCODE_API_KEY=dummy`（既有 `vlm.load_api_key`
   先于缓存查找，见 04/05 handoff）；与本次分类无关，仍待网关化修复。
4. **`scripts/run_tests.sh` 依赖 zsh**：与仓库现有 `build_macos_app.sh` 一致（`#!/bin/zsh`）。

## 6. 隔离确认

提交 `987fb26` 仅含 `pyproject.toml`、`tests/{taxonomy,conftest,test_taxonomy}.py`、
`scripts/run_tests.sh`、`docs/{testing,setup}.md`、`docs/agents/parallel-dev.md`；
未修改任何 `tests/test_*.py`（除新增 test_taxonomy.py），无密钥/凭证。

## 7. suggested skills

- `diagnose`（若后续 strict-markers 或 scoped-run 出现误排除/误纳入）
