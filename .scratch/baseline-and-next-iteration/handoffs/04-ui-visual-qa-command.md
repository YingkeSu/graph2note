# Handoff 04 — 建立 UI 截图视觉验收命令

> 来源：`issues/04-ui-visual-qa-command.md`（Status: in-review）。
> 消费者：issue 05（内容视觉验收沿用 Budget/指纹/重放/错误语义）、dispatcher 验收、后续开发者。
> 分支：`ao/graph2note-13/root`，实现提交 `f118f79`。

## 1. 完成了什么

`graph2note visual-qa` 开发者命令（开发工具，不新增产品 UI/面向用户的调用流程）：

- `graph2note/visualqa.py`（单模块，避免改动 pyproject.toml 的 packages 清单）：
  - `ScenarioSpec` / `Budget`：场景（scene/viewport/expectations/planted/prompt_version）与预算
    （max_calls/max_tokens/timeout_seconds/total_timeout_seconds）。
  - `check_ui(screenshot, spec, ...)`：截图 + 场景预期 → 视觉 LLM → 结构化 JSON 报告；
    默认通道 `kimi` / `kimi-k2.6`（可 `--provider/--model` 及 env `GRAPH2NOTE_VISUALQA_*` 覆盖）。
  - 报告字段：`tool/mode/status/verdict/caveat/scene/viewport/provider/model/prompt_version/
    input{screenshot_fingerprint,scenario_fingerprint}/budget/usage/timing/observations/issues
    {severity,evidence,region,uncertainty,suggestion,matched_planted}/limitations/planted/
    correspondence{matched,missed,unmatched_model_issues}/error/replay`。
  - 确定性输入指纹（sha256 截图字节 + 场景 JSON 规范化）；`save_raw_record`/`render_report_from_record`
    离线重放（重放路径零网络）。
  - 可插拔截图 `capture_screenshot`（headless-chrome / macos-screencapture），后端可注入（离线测试）。
  - 错误语义：超时→`timeout`、认证→`auth`、网关→`gateway_error`、非法输出→`invalid_output`、
    总时长→`total_timeout`，全部 `status="incomplete"`、`verdict=None`，绝不显示「通过」。
- `graph2note/cli.py`：新增 `visual-qa capture|ui` 子命令分发（`ui` 支持 `--screenshot`/
  `--capture-url`/`--scenario`/`--replay`/`--save-raw` 及预算开关）。

测试与 golden（全部离线、零凭证、零网络）：

- `tests/test_visualqa.py`（26）、`tests/test_cli_visualqa.py`（6）。
- `tests/golden/visualqa/ui-normal.review.json`：真实录制的 Kimi 空文档库截图评审
  （取自 ASSESSMENT §3 live 探测的 ui case，observations/limitations + issues=[]）。
- `tests/golden/visualqa/ui-defect.review.json`：**合成**缺陷评审（重叠 + 底部裁切），
  对应 PIL 生成的预埋缺陷截图，用于 correspondence 验证（已标注为合成，见 §5 待办）。

## 2. 如何运行测试

```bash
# 全量（当前 opencode key 已退役，9 个既有「缓存种子」测试在 vlm.load_api_key 先于缓存
# 查找执行，需一个非空 dummy key 才能通过——该值只在缓存命中前被读一次，绝不触发网络）：
OPENCODE_API_KEY=dummy uv run pytest -q     # 382 passed, 2 skipped
# 仅本切片：
uv run pytest tests/test_visualqa.py tests/test_cli_visualqa.py -q   # 31 passed
```

开发命令（真实调用需 KIMI_API_KEY，见 §5 待办）：

```bash
# 已有本地截图输入
graph2note visual-qa ui --screenshot shot.png --scene library-empty \
  --expectation "空状态有引导" -o report.json --save-raw record.json
# 从 URL 截图 + 检查（一条命令）
graph2note visual-qa ui --capture-url http://127.0.0.1:8000/ --viewport 1440x1000 -o report.json
# 离线重放已保存的原始响应（零网络）
graph2note visual-qa ui --replay record.json -o report.json
# 只截图
graph2note visual-qa capture http://127.0.0.1:8000/ -o shot.png --viewport 1440x1000
```

## 3. 决策与对 spec 的偏离

- **单模块而非子包**：受隔离约束（不得改 `pyproject.toml`），`visualqa.py` 放入既有 `graph2note`
  包内，避免新增 packages 清单条目；核心（Budget/指纹/重放/错误语义）按可复用结构组织，供 issue 05
  加内容模式。
- **默认通道 Kimi/kimi-k2.6**（ASSESSMENT §3 已 live 验证）。偏离：本 worktree 的
  `eval/gateway.py` 尚未注册 `kimi` provider（该注册是主检出**未提交**改动，归 issue 03 归档），
  故当前默认 provider 实时调用会报「未知 provider=kimi」——见 §5。
- **调用不默认重试非法输出之外的情况**：超时/认证失败不重试（fail fast，与 ASSESSMENT §3
  「不重试」一致）；仅非法输出在 `max_calls` 内重试。
- **correspondence 为确定性 best-effort**（region/kind 关键词匹配），用于记录模型判断与
  人工/确定性证据的对应，不做发布门槛；单次 LLM 通过不是验收唯一条件（报告 `caveat` 显式声明）。

## 4. AC 证据对照

- AC1 完整可重复命令 + 本地截图输入：`tests/test_cli_visualqa.py`（ui/capture/replay 全路径），
  真实 headless-chrome 截图已 smoke 通过（`capture data:… → captured.png`）。
- AC2 报告字段 + 不推断交互：`test_ui_prompt_records_scenario_viewport_and_interaction_guard`、
  `test_check_ui_complete_no_issues`（指纹/limitations/caveat）、`test_parse_ui_review_normalizes_and_validates`。
- AC3 边界 + 未完成不显示通过：`test_invalid_output_is_incomplete_and_retries_bounded`、
  `test_timeout_is_incomplete_and_not_retried`、`test_auth_failure_is_incomplete`、
  `test_gateway_error_is_incomplete`、`test_total_timeout_bound_enforced`、
  `test_incomplete_never_reports_pass`、`test_cli_ui_timeout_exit_nonzero_and_not_pass`。
- AC4 usage/耗时/重放 + 离线无凭证：`test_save_raw_and_replay_without_network`、
  `test_replay_invalid_record_reports_incomplete`；所有测试注入 call_fn，不经 `load_api_key`/网络。
- AC5 正常 + 预埋裁切/重叠样例 + 对应：`test_check_ui_complete_no_issues`（真实录制正常页）、
  `test_check_ui_issues_match_planted_defects`、`test_check_ui_unmatched_model_issue_recorded`。

## 5. 未尽事项 / 上游集成待办

1. **Kimi 网关注册（issue 03）**：`eval/gateway.py` 的 `kimi` provider 注册目前只在主检出
  未提交，本 worktree 没有。issue 03 归档合并后，`visual-qa ui` 默认 kimi 实时调用方可工作；
  届时需对真实 Library 页面跑一次 live 验收并核对 usage。
2. **缺陷样例的实时录制**：`ui-defect.review.json` 是合成评审（已明确标注）。上游集成后建议
   对真实预埋缺陷页面录制一条真实响应替换，量化误报/漏报。
3. **全量测试的 dummy key**：9 个既有缓存种子测试因 `graph2note/vlm.py::load_api_key` 在缓存
   查找前执行而需要非空 `OPENCODE_API_KEY`；这是既有问题，归 issue 03/01 网关化修复，本切片未改。
4. **issue 05 内容模式**：复用 `Budget`/指纹/重放/`InvalidReviewOutput`/错误语义，新增内容
   prompt 与差异口径（source/output evidence、kind 分类），与 UI 模式分开维护样例。

## 6. 隔离确认

未改动 `pyproject.toml`、`uv.lock`、`eval/gateway.py`、`tests/test_llm_settings.py`；
`.scratch/baseline-and-next-iteration/` 下仅新增本 handoff 与 issue 04 的 Status/AC/Comments
（按编排指示，未提交进分支）。提交 `f118f79` 仅含 `graph2note/visualqa.py`、`graph2note/cli.py`
与 `tests/`（无密钥/凭证）。

## 7. suggested skills

- `impeccable`（后续对三栏 Web 界面做视觉评审时的 UI 复核）
- `diagnose`（若后续真实页面的视觉 QA 出现误报/漏报需要归因）
