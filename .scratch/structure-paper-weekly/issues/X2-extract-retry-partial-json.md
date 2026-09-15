# X2 — 抽取重试缺口：半截 JSON 不触发预算升级重试

Status: ready-for-review

来源：`/tmp/review-spw-D5a-verdict.md` §4.1/§7-R1；`/tmp/spw-final-vision-report.md` §5-2；BOARD D5a 行残留「R1 截断 parse_fail」。属 D 轨遗留（X 轨）。

## What to build

`graph2note/diagram.py::extract_diagram_image` 的重试条件目前只覆盖「预算耗尽且**正文为空**」：

```python
if attempt == 0 and finish == "length" and not (content or "").strip():
    continue  # reasoning exhausted with empty content -> one upgraded retry
```

当返回**非空但被截断**的半截 JSON（`finish_reason=length`、`content_len>0`）时直接 `break`，随后 `try_parse_json` 失败 → `verdict="parse_fail"` 走降级，不触发 10000 预算升级重试。

实测：D5a reviewer run 2 的 01——1 次 HTTP 调用，8000 预算 → `length` + `content_len=524`（半截）→ `parse_fail`，无第二次尝试（`/tmp/review-spw-D5a-verdict.md` §4.1）。新 prompt 更长、输出更丰富，截断概率上升。

要求：把「`length` + 非空但解析失败」纳入一次升级预算重试，或提高 diagram 默认输出预算以降低截断概率。

## Acceptance criteria

- [ ] 重试条件扩展：`finish_reason=length` 且（正文为空 **或** 正文解析失败）时，在 attempt 0 触发一次升级 `retry_tokens` 重试；非 `length` 的解析失败仍不重试（不引入同参重试，与既有「no same-params retry」约定一致）。
- [ ] 离线单测（可注入 `_post`/fake gateway）：①空正文 length → 重试（既有行为不回归）；②非空 length + 不可解析 → 重试；③非空 length + 可解析 → 不重试（避免浪费）；④非 length 的 parse_fail → 不重试。
- [ ] 重试后仍失败的行为与现状一致（降级 → `verdict="parse_fail"`，`meta.attempts` 记录两次、`meta.retried=true`）。
- [ ] mutation 有牙：把「非空 length 也重试」条件改回旧行为时新测试变红。
- [ ] 全量 `pytest -p no:warnings` 绿；`meta.attempts`/`retried` 与 D4 F-H 预算升级语义（8000→10000）一致。

## Blocked by

无。

## 领地

- 独占：`graph2note/diagram.py`（`extract_diagram_image` 重试分支 + 相关常量）、`tests/test_diagram_*.py` 内新增用例。
- 禁止：渲染层、`_layout.py`、I 轨文件。

## Comments

- 与 X1 同源：X1 解决通道可用性（kimi 空内容），本项解决「返回了但截断」的损耗。
- 现有注释与语义：`No same-parameter retry on empty ... only a finish_reason=length (reasoning exhaustion) triggers one upgraded-budget retry`（`graph2note/diagram.py` 的 docstring）。

### 交付记录（2026，dev/X2-extract-retry）

分支 `dev/X2-extract-retry`（基于 main b56e3c4，未 push；worktree `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-108`）。

改动：
- `graph2note/diagram.py`：`extract_diagram_image` 的重试分支拆成三条显式规则——非 `length` 有正文 -> 直接用；`length` + 正文可 `try_parse_json` -> 直接用（不浪费重试）；`attempt==0` 且 `length`（正文为空**或**截断不可解析）-> `continue` 升级 `retry_tokens`（8000→10000）；`length` + 非空不可解析的重试仍失败则 `break` 走既有 `parse_fail` 降级。docstring 同步说明「截断不可解析也重试、其余 parse_fail 不重试」。
- `tests/test_diagram_retry_partial_json.py`（新文件，7 例，离线 fake `_post`）：①空正文 length 重试（回归护栏）；②非空 length 不可解析 -> 2 次调用、8000→10000、第二次成功则 ok；③非空 length 可解析 -> 1 次调用不重试；④非 length parse_fail -> 1 次调用不重试；⑤重试后仍失败 -> `parse_fail` + `attempts=2` + `retried=true`；另加空正文非 length 不重试、升级重试带「直出 JSON」system 追加两条护栏。
- `tests/taxonomy.py`：新测试文件登记模块归属 `diagrams`（`tests/test_taxonomy.py` 的覆盖元测试强制要求，1 行）。

证据：
- 全量 `/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest -p no:warnings` -> `1214 passed`，EXIT=0（基线 1207 + 新增 7）。
- mutation 有牙：把重试条件改回旧行为（`length` 且仅正文为空才重试）后，新文件 3 例变红；只去掉「可解析则不重试」一行的第二处 mutation 让 ③ 变红。
- 验收逐条证据见 `/tmp/spw-X2-done-report.md`。

截图/演示：无（纯离线重试策略改动，无可视化产物）。
