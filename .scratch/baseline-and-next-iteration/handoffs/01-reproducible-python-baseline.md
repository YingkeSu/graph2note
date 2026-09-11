# Handoff — issue 01：恢复可复现的 Python 安装与运行基线

Branch: `ao/graph2note-10/01-reproducible-python-baseline`
Worktree: `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-10`（基于 main `6caaef9`）

## 完成了什么

从干净环境安装、测试、运行项目所必需的依赖与打包前置整理，无产品功能扩展。

1. **依赖声明**（`pyproject.toml`）：
   - `dev` extra 补 `httpx>=0.27`（FastAPI TestClient 的运行时依赖，此前未声明，见 ASSESSMENT §2）。
   - 新增 `diagram` extra：`graphviz>=0.20` + `matplotlib>=3.5`（issue 05 确定性渲染的声明落库，此前也是「手动补装」）。
   - 新增 `all` extra（一键装全）。
   - `[tool.setuptools] packages` 补 `graph2note.notes` 与 `eval`（wheel 漏包根因：`graph2note.notes` / `eval` 运行时被 `graph2note.cli`/`graph2note.llm_settings`/`graph2note.vlm` 等 import，但不在打包清单）。
2. **锁文件**：`uv lock` 重生成 `uv.lock`（新增 graphviz/httpx/matplotlib 及传递依赖，exit 0）。
3. **离线缓存路径修复**（`graph2note/vlm.py::call_ir`）：`load_api_key()` 原本在 cache 命中检查**之前**被调用，导致「offline via seeded cache」测试在没有 `.env` 的干净环境必然失败（`未找到 OPENCODE_API_KEY`）。将 key 解析移到 cache 命中分支之后——cache 命中完全离线（无需密钥/会话），未命中路径行为不变。
4. **文档**（`docs/setup.md`）：前置、extras 组合、`uv sync --all-extras`、测试、运行（CLI/Web/notes-export）、wheel 构建 + 独立环境验证、供应商配置说明。

## 如何运行测试

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-10
uv sync --all-extras        # 或已就绪的 .venv
uv run pytest               # 353 passed, 0 failed, 0 skipped（43.29s）
```

## 验收证据（逐条）

- **AC1 依赖组合 + 锁一致 + 文档命令可重复**：`uv lock` exit 0；`uv run graph2note examples/note.ir.json --stdout` 与 `uv run uvicorn graph2note.webapp:create_app --factory` 实测可跑（文档命令与实现一致）。
- **AC2 wheel + 独立环境验证**：`uv build --wheel` exit 0 → `/tmp/g2n_wheel/graph2note-0.1.0-py3-none-any.whl`（74 文件，含 `graph2note/notes/` 与 `eval/`）；独立 venv `/tmp/g2n_iso/venv` 装 `whl[all]` exit 0；`/tmp/g2n_iso/verify.py`（cwd=/tmp，断言 repo 不在 sys.path）四步全过：运行时导入 OK、Web 启动 OK（create_app+/api/documents→200）、CLI IR→MD OK、fixture Vault 导出 OK（3 个 .md）。
- **AC3 供应商离线契约**：`tests/test_gateway_select.py`(12) + `tests/test_llm_settings.py`(9) = **21 passed**，全部离线（monkeypatch urlopen / 显式 setenv / tmp_path），不依赖真实密钥与默认供应商；worktree 无 `.env`。
- **AC4 全量测试**：`353 passed, 0 failed, 0 skipped`。0 skip 的原因：本机 `dot`(graphviz 14.1.2) 与 `tesseract`(5.5.2) 均存在，`diagram` extra 又提供了 matplotlib/graphviz python 包。缺失时的跳过点（已写入 docs/setup.md）：`tests/test_ocr.py`（tesseract/chi_sim）、`tests/test_diagrams.py` 中 graphviz 两例（dot/graphviz pkg）、`tests/test_ingest_pdf.py`（pymupdf）。
- **AC5 证据**：日志 `/tmp/g2n_uv_lock.log`、`/tmp/g2n_uv_sync_all.log`、`/tmp/g2n_build_wheel.log`、`/tmp/g2n_iso_install.log`；产物 `/tmp/g2n_wheel/*.whl`。无产品功能扩展。

## 决策与对 spec 的偏离

- **`eval` 打包为顶层包而非重构**：`graph2note` 核心模块 import `eval.gateway`，最小必要改动是把 `eval` 加入 packages 清单；不重构 `eval` 的归属（超出本 issue「必要的打包整理」范围，且属产品结构决策）。
- **`diagram` extra 把 graphviz + matplotlib 放同一组合**：两者是「首选/回退」关系，同装后引擎按 `dot` 可用性自动选择；不拆两个 extra 以免过度设计。
- **修 `call_ir` 的 eager key 加载**：属「恢复可复现运行基线」的必要 bug 修复（否则干净环境跑不过离线 cache 测试）；行为等价，仅重排 key 解析时机。
- **偏离**：未为 Kimi 通道新增离线测试——Kimi 通道在 `eval/gateway.py` 的**未提交改动**里（issue 03 归档），6caaef9 已提交态只有 opencode/deepseek；AC3 的 Kimi 覆盖随 issue 03 落地。

## 与主检出在途改动的冲突（供 issue 03 归档时参考）

主检出 `/Users/suyingke/Programs/OHO/graph2note` 有未提交改动，本分支的依赖改动会与之**语义重叠**（非 git 冲突，因为本分支从 6caaef9 干净提交态出发）：

- `pyproject.toml`：主检出未提交态加了 `macos` extra（numpy/pywebview/pyinstaller）；本分支加了 httpx/diagram/all extra + packages。归档时需**合并两套 extra**（保留 macos + 本分支新增）。
- `uv.lock`：同理，主检出未提交 lock 含 macos 依赖；本分支 lock 含 httpx/matplotlib/graphviz。归档时重新 `uv lock` 取并集。
- `eval/gateway.py`、`tests/test_llm_settings.py`（Kimi 接入）：属 issue 03，本分支**未触碰**；但 `tests/test_llm_settings.py` 的 providers 集合断言（`== {"opencode","deepseek"}`）在 Kimi 加入后需同步为三元组。

## 未尽事项

- Kimi 通道离线契约覆盖（随 issue 03）。
- `graph2note/notes` 与 `eval` 若后续要拆出独立发布物，需重新讨论边界（本轮仅按最小必要打包）。
- 文档中的 `uv run` 命令假设已 `uv sync`；纯 pip 用户可用等价 `python -m venv + pip install .[all]`（未逐条实测 pip 路径，uv 已实测）。
- 未引入 CI（仓库无 CI，见 issue 03 AC5 口径）。

## Suggested skills

- `diagnose`：若独立环境验证出现「能 import 但行为异常」类问题，用于定位 wheel 漏包 / 依赖版本漂移。
- 本 issue 纯 Python + pytest，无 UI；`impeccable`/`prototype` 不适用。
