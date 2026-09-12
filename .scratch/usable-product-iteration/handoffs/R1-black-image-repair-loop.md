# Handoff — R1 黑图存量检测与重解析闭环

Branch: `dev/r1-black-image-repair`（worktree `graph2note-18`，基于本地 main `fd10919`，未 push、未开 PR） · Status → ready-for-review

## 交付范围

把 `fix-black-preprocess` handoff 的"建议后续动作"产品化为**检测 → 报告 → 确认 → 从 `preprocessed_raw.png` 重跑 → 验收**的闭环。新增模块 `graph2note/repair.py`；三个入口（CLI / API / Web）全部接线。**未改 `preprocess.py`**（修复管线本身已就绪）。

### 1. 检测规则（`repair.scan_library`，纯离线）

只看文档**最新版本**，逐篇输出 4 类之一：

| 状态 | 判定 | 进入重跑队列 |
|---|---|---|
| `black` | `preprocessed.png` 灰度均值 < 10（或文件缺失但有 raw） | ✅ |
| `suspected` | Markdown 命中"空白页/纯黑"占位特征（空 Markdown 也算） | ✅ |
| `needs_reupload` | `preprocessed_raw.png` 缺失 | ❌（单独列出，`error_kind=needs_reupload`） |
| `healthy` | 其余 | ❌ |

报告含每篇 `pages`（单图文档=1）、`estimated_vlm_calls`、均值/墨迹、可修复名单，以及 summary 计数与 `black/suspected/needs_reupload/repairable` 名单数组。扫描只读文件、**零 LLM 调用**（测试用 `monkeypatch` 把 `vlm.call_ir` 换成抛错来钉死这一点）。

### 2. 重跑路径（`repair.run_job` / `run_repair`）

- 从 `preprocessed_raw.png` 走 `pipeline.parse_document`（预处理 → router → IR → Markdown），`save_document` 在**同 doc_id 追加新版本**。
- **旧版本、旧 `preprocessed.png`、`preprocessed_raw.png` 一律不覆盖、不删除**（测试逐字节断言）。
- 验收口径（与 handoff 一致）：新 `preprocessed.png` 均值 > 150、墨迹占比 > 0.005（源页本身无墨迹的空白页放宽墨迹项）、Markdown 非空白占位。未通过则 `status=failed, error_kind=verify`（版本仍入库，便于重试）。
- 逐篇结果落盘 `<storage>/repair/<repair_id>/job.json`（每篇一次 checkpoint）+ 结束时 `report.json`；`repair.load_jobs` 启动时恢复并把中断任务标 `interrupted`；失败可 `run_job(only=[...])` 或 `POST /api/repair/{id}/retry` 重试。
- 预算：`estimated_vlm_calls` 在 dry-run 计算（可修复篇 × 页数），执行时 `vlm_calls` 逐篇累加；fixture 下断言两者相等（stub 单次成功，无重试）。

### 3. 三个入口

- **CLI**：`graph2note repair scan [--json]`、`graph2note repair run [--doc ID ...] [--yes] [--model M]`。`run` 默认 dry-run（只打印计划），`--yes` 才真实调用；`--doc` 可重复、缺省=全部可修复。
- **API**：`POST /api/repair/scan`（只读报告，可带 `document_ids` 过滤）；`POST /api/repair/run`（**必须**显式 `document_ids` + `confirm=true`，否则 422/400；未知 id 404）；`GET /api/repair/{id}`（轮询进度，per-doc 状态）；`POST /api/repair/{id}/retry`；`GET /api/repair`（任务列表）。
- **Web**：新增自包含视图 `graph2note/webstatic/repair.js`（`index.html` 仅加一行 `<script>`）。顶栏注入「修复报告」入口，展示检测名单 + 预估成本，点击「确认并开始修复」后 POST 显式 id + `confirm:true`，复用 PDF 批任务的 job 模式轮询 `/api/repair/{id}`；失败项可一键重试。**未改 `app.js`**，避免与同期 U1（webstatic 重构）冲突。

### 4. 与 S2 / A1 的约定

- **S2 版本来源字段**：重跑新版本在 `record.json` 的版本元数据中写入
  `"provenance": "repair"` + `"provenance_detail": {"source":"preprocessed_raw","repair_id","old_version_id","repaired_at","model"}`。
  同时 `get_document` 的 enriched `versions[]` 与 `latest` 块都透出 `provenance`，S2 可直接消费，无需猜。
  常量：`graph2note.repair.PROVENANCE_REPAIR`。其它入库路径 `provenance=None`（不写该字段，S2 可视为 `parse`）。
- **A1 自动打标接线点**：`repair.run_job(..., after_commit=callback)` 是**唯一**入库后回调缝，签名
  `callback(store, document_id, parse_result, record)`；单次提交点在 `repair._repair_one` 内（先 `save_document` 成功、再调回调）。
  打标异常被捕获、只记 warning，**不阻塞修复**。Web 侧接线封装在 `JobRunner._wrapper_repair`（`webapp.py`），A1 只需在 `repair.run_job` 调用处传/包一层 callback，无需改三处入口。

## 离线测试（`tests/test_repair.py`，新增 19 个）

fixture 文档库覆盖黑图 / 正常 / 缺 raw / 疑似空白四类（`_healthy_image`/`_black_image` 合成图 + golden IR stub router）。

- scan 四类分类、页数、预估调用数、子集过滤、`plan` 对缺 raw 与未知 id 的 skip；
- 占位检测器（空/纯黑/`此页无内容` 命中；正常 Markdown 不命中）；
- run 默认 dry-run 不建版本；`--yes`（stub）追加新版本、旧版本与 raw 逐字节不变、新图均值>150/墨迹>0.005、解析非空白；
- `provenance=repair` + `provenance_detail` 断言（含 enriched latest）；
- **预算准确**：dry-run 预估 == `job.vlm_calls` == stub 实际调用次数；
- 缺 raw 文档 skip 且零调用；job.json 重载可查；未通过验收 → `failed` + 可重试（第三次版本）；
- `after_commit` 回调（A1 缝）；
- CLI：`scan --json` 离线、`run` 默认 dry-run、`run --yes` 走 stub 并打印预算；
- API：scan 分类、run 缺 id→422 / 缺 confirm→400 / 未知 id→404 / 正常→job 轮询成功且实际调用==预估；retry 端点；`GET /` 含 `/static/repair.js` 且静态文件 200。

**全量 `uv run pytest`：499 passed（85.9s）**，含新增 19 个；无真实网络调用。分类登记：`test_repair → webapp`（integration）。

## 真实库修复（预算流程 + 结果）

用户真实库：`~/Library/Application Support/Graph2Note/storage/documents/`。

**流程（按 task 要求：先 dry-run 核对名单/预算，再 `--yes`）**

1. dry-run scan（只读，0 调用）：
   `{"total":43,"black":0,"suspected":1,"needs_reupload":0,"healthy":42,"repairable":1,"estimated_vlm_calls":1}`
2. 核对：**黑图名单为空**（与 issue 基线的"22 篇黑图"不符，见下"偏差说明"）；唯一可修复项是 1 篇**疑似空白**（`doc-9ddad73fc1`，最新版本 Markdown 0 字符）。预估 1 次 VLM 调用，规模合理。
3. `--yes` 真实重跑（网关 deepseek，settings=`<support>/llm-settings.json`，未改 `.env`、未打印凭据）：
   `graph2note repair run --yes --doc doc-9ddad73fc1`
   - 结果：`status=done`，**预估 1 == 实际 1**；`doc-9ddad73fc1 → success`，新版本 `v1789179179109-4`，
     `post_mean=237.982`、`post_ink=0.050809`、Markdown 1331 字符、非空白占位、`verified=true`；
   - 旧 4 个版本（含纯黑 v-0、空 Markdown v-3）与 `preprocessed_raw.png` 原样保留；
   - 新版本 `provenance=repair`，`repair_id=repair-20260912101227-dfd18f`。
4. 修后复扫：`{"total":43,"black":0,"suspected":0,"needs_reupload":0,"healthy":43,"repairable":0}`。

**修复前后黑图计数：0 → 0；疑似空白：1 → 0。** 全库 43 篇最新版本均为健康图。

### 偏差说明（"22 篇黑图"为何实测为 0）

issue/BOARD 写的"2026-09-12 实测 43 篇中 22 篇仍为黑图"是**修复批次执行中途的快照**，不是稳态：

- 黑图 bug 修复合并于 `c6f8c52`（01:37）；
- 上一轮 worker 已于 **02:24–02:28 用修复后网关 deepseek 重跑 40/40 篇黑图**，报告见 `baseline-and-next-iteration` 分支提交 `0e6d026`（"reparse execution report — 40/40 black-image docs re-parsed via deepseek"）；`documents/*/record.json` 中 40 个新版本 `created_at` 均为 2026-09-12T02:2x，可复核；
- 22 = 02:24 批次执行到一半时"已修 18 / 待修 22"的时刻值（UI 实地考察截图即取自该窗口）。
- 本次 R1 的独立扫描（同一规则：最新版本均值 < 10）确认**黑图 = 0**；"22 → 0"的修复实际由 `0e6d026` 那一轮完成，本 issue 不改动该结论、也不重复调用。

**例外/遗留**：库中仍保留 **47 个历史黑图版本**（`versions/<vid>/preprocessed.png` 均值 0）——这是"旧版本不覆盖"的预期结果，R1 检测只看最新版本，不影响可回退。`doc-9ddad73fc1` 的疑似空白是该文档 09:23 用户实时会话产生的空 Markdown（非黑图 bug），本次已通过 R1 重跑修复为 v-4。

## 验证证据摘要

- 检测口径钉死：`BLACK_MEAN_THRESHOLD=10`、验收 `HEALTHY_MEAN_TARGET=150`/`HEALTHY_INK_TARGET=0.005`/`INK_PIXEL_LEVEL=128`（`tests/test_repair.py` + `repair.py` 常量）。
- 真实库修复前后计数如上；新图均值 237.98、墨迹 5.08%。
- 预算准确：fixture `job.vlm_calls == estimated_vlm_calls == stub 调用数`；真实库 1 == 1。
- 只读 `preprocess.py`、未动 `issues/*.md`、`BOARD.md`、`webstatic/app.js`。

## 已知限制 / follow-ups

- "页数"对当前单图/单 PDF 页文档恒为 1；若将来一个 version 承载多页，`pages` 需从版本内页图数推导（当前 `DocumentFinding.pages` 已留字段）。
- `estimated_vlm_calls` 以"每次页面解析 = 1 次视觉调用"计；若页面触发条件性的 diagram 二次视觉调用或 IR 校验重试，实际调用会多于预估（fixture stub 不重试所以相等）。预算口径已在 `repair.py` 文档化。
- 空 Markdown 被计为 `suspected`（真页解析不应产出空串）；这会把"解析彻底失败"的文档纳入可修复队列，符合 R1 意图，但会把纯粹的空内容页也报出来，需人工在 Web 上确认（可修复名单可逐个取消）。
- 真实库修复需要一个可用视觉网关；本次用 deepseek（settings 文件解析），main checkout `.env` 提供 key。未在 worktree 内硬编码任何凭据。

## 变更文件

- 新增 `graph2note/repair.py`、`graph2note/webstatic/repair.js`、`tests/test_repair.py`
- 修改 `graph2note/cli.py`（repair scan/run）、`graph2note/webapp.py`（API + JobRunner + 启动恢复）、`graph2note/store.py`（版本 `provenance`/`provenance_detail`）、`graph2note/webstatic/index.html`（1 行 script）、`tests/taxonomy.py`（登记）
