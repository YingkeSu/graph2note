# 测试整理分类与模块级测试运行

Status: merged

来源：维护者指令（2026-09-12）：「整理并分类一下测试。之后单模块的开发不必要做全量测试，仅当大版本更新前做全量测试。」

## What to build

把测试套件按模块/层次整理分类，建立模块级测试运行方式，并把「单模块开发只跑相关测试、大版本合并前才全量」制度化到开发协议与文档。

- 测试分类：用 pytest markers 按维度标注（建议维度：模块归属——ir/render/preprocess/pipeline/ingest/verify/webapp/notes/visualqa/eval/diagrams 等；层次——unit/integration；成本——slow、live-llm、gui）。
- `pyproject.toml` 注册全部 markers 并开启 `--strict-markers`，消除 unknown-marker 警告。
- 提供可文档化的模块级运行命令（如 `pytest -m webapp`、`pytest tests/test_webapp*.py`、或一个 `scripts/run_tests.sh <module>` / uv 脚本），并给出「改了模块 X 应跑哪些测试」的映射表（含邻近受影响模块的最小集合）。
- 只做分类与运行方式，不改变任何测试行为、不删除测试；现有全量套件保持一键可跑且全绿。
- 制度化：更新 docs/agents/parallel-dev.md §6 验收条款（单模块交付=模块范围测试绿+受影响邻近测试；大版本/发布合并前=全量套件绿）与 docs/setup.md 的测试运行说明。

## Acceptance criteria

- [ ] 每个测试文件至少有一个模块归属 marker；`--strict-markers` 下无未注册 marker
- [ ] 模块→测试映射表入库（docs），单模块交付的最小测试集可按表一键执行
- [ ] 全量套件行为不变：分类后全量运行结果与分类前一致（数量、通过/跳过逐项一致）
- [ ] parallel-dev.md §6 与 docs/setup.md 已更新为新测试政策
- [ ] 不触碰在途分支正在修改的测试文件内容（07/08/black-fix 的相关新测试文件只读参考，分类标注如遇冲突记录在 handoff 留合并后处理）

## Blocked by

None - can start immediately（基于最新 main；注意与在途分支的潜在 rebase）
