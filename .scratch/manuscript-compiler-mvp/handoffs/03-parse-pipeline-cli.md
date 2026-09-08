# Handoff 03 — 解析 tracer：预处理 → Router → VLM → IR → CLI 出 .md

> 来源：`issues/03-parse-pipeline-cli.md`（Status: in-review）。
> 消费者：issue 06（Web UI 复用 `parse_document`）、issue 09（PDF 拆分复用 Router/管线）、
> issue 10（双模型交叉校验，接 `verify_second_model`）、issue 11（速度优化，接分阶段计时与 `candidate_models`）、
> 后续维护者。
> VLM 网关：`docs/llm/opencode-go.md`（opencode go 网关）；实时选型待 issue 01 结论，见「网关现状」。

## 1. 交付内容

`graph2note parse <image> -o <out.md>` 一条命令完成首条真实端到端链路：

`手稿图片 → 预处理（独立固定阶段）→ Recognition Router（恒走 Route A）→ 视觉 LLM → 校验通过的 Document IR → 确定性 Markdown 渲染 → .md + 真实附件资产 + 分阶段计时 JSON`

新产品模块（均懒加载成像依赖，`import graph2note` 不依赖 PIL/numpy，CI 可离线）：

- `preprocess.py`：EXIF 方向与内容判定结合（矛盾以内容为准，FR-002）、内容 90° 旋转判定、歪斜 deskew
  （−6..6° 投影投影评分）、自动页面角点透视校正（连通域+SVD 单应）、边缘裁剪、对比度分位拉伸；各阶段可落盘查看。
  **确定性**：同一输入字节 → 同一 `_stage_final.png`（回归测试校验字节一致）。修复：`save_stages=False` 时仍保证输出 final 图。
- `router.py`：`RecognitionRouter` 统一入口接口（上游不可绕过，FR-004）；
  `RouteARouter` MVP 实现恒走 Route A。**P1 扩展缝已声明未实现**：
  `candidate_models`→issue 11、`verify_second_model`→issue 10、`route_b`→OCR 路线。
  校验/重试/降级：模型回复 → schema 校验，非法重试（`max_retries`），最终失败 `RecognitionError` 明确报错；
  空回复 → 降级为空 IR（不崩溃）；结构空 diagram/flow → 注入 `source` 走 issue 05 的 crop 降级路径。
- `vlm.py`：opencode go 网关封装；`parse_ir_json`（围栏剥离+平衡花括号 JSON 提取）；`VlmCache`（磁盘缓存，
  按图片字节+model+prompt 键控）；`load_api_key`（env → worktree .env → main checkout .env，从不入库）。
  **网络全部隔离在这里**，router/pipeline/CLI 与测试保持离线。
- `timing.py`（`StageTimer`/`NullTimer`）：分阶段计时 → JSON（issue 11 基线喂给器）。
- `pipeline.py`：`parse_document` 编排 preprocess/llm/render 三个计时阶段，产出 `.md`、`assets/`、`preprocessed/`、
  `timing.json`；`timing.json` 增补 `llm` 记录（attempts/retries/reasoning_tokens/latency），喂 issue 11 基线。
- `cli.py`：新增 `parse` 子命令；**保留**旧的 IR→Markdown 默认编译入口（issue 02 契约不破坏）。

新测试（离线、无 live）：`test_preprocess.py`（合成图旋转/歪斜/透视/EXIF 定标）、`test_router.py`（路由入口、
非法 IR 重试、空降级、P1 缝）、`test_vlm.py`、`test_pipeline.py`（全链离线+计时+确定性）、
`test_cli_parse.py`（CLI parse 离线经 seed 缓存+错误路径）、`test_e2e_images.py`（真实 `test-images/02` 全链）。
golden：`tests/golden/`（真机录制，见 §3/§4）。合计 **92 passed, 2 skipped**（skip 为 graphviz 缺失，属 issue 05）。

## 2. 关键决策

- **Router 不可绕过**：`recognition` 只经 `RecognitionRouter.recognize`，调用方/测试绝不直连模型。
  测试通过可注入 `caller(image, model, recover?) -> (content, meta)` 复用 golden，CI 无网络。
- **非法 IR 重试**：非法回复 → 重试（`recover=True` 收紧 prompt），打满 `max_retries` 抛 `RecognitionError`（明确错误，非崩溃）。
- **空回复降级**：`content==""` → 空 IR（blocks=[]），不清零其他装配，绝不 crash；警告记录原因。
- **结构性空 diagram 降级**：无 nodes/edges 的 diagram/flow → 注入 `source=预处理后图路径` → 渲染走 issue 05 crop，产出真实资产。
- **延迟策略对齐 main e0bd5dc 诊断**：固定直出 session（R1）、首调直出+中等 max_tokens（默认 3500，可 env `GRAPH2NOTE_MAX_TOKENS` 覆盖）、
  图片送模型前降采样到最长边 1024 / q85 JPEG（R3）、硬超时 120s + 重试切策略（R4）、reasoning_tokens 记入 timing（R5/issue 11）。

## 3. 网关现状与 golden 录制（重要）

实时调用依 `eval/gateway.py` 修复（worker 5，dev/gateway-speed-fix）尚在落地，**修复合并后需复审**——
worker 5 完成 `merge main e0bd5dc` 后，本 worker 建议按 §订阅更新号重新对齐（R1 会话固化告警等）。

- `02-digitize-pipeline.jpg`：**已录制真实有效 IR**（`tests/golden/real-img02-digitize.golden.json`，glm-5.3-flash 一次成功，
  155s，finish=stop）。`test_e2e_images.py::test_real_image_02_renders_structure` 用它对两条真实手稿做**完整离线全链**：
  预处理（含方向/歪斜/透视定标）→ 缓存命中 → IR 校验 → 渲染 → assets → 计时，零网络，断言结构正确 Markdown + 附件完整。
- `01-requirements-arch.jpg`（架构白板大图，以图表为主）：glm-5.3-flash 当前**稳定返回空正文**
  （`finish_reason=length`，reasoning 吃掉 max_tokens，95–274s）——正是上节延迟诊断的根因。已录制为
  `tests/golden/real-img01-empty.golden.json`（空），对应测试 `test_real_image_01_empty_reply_degrades_cleanly`：
  **断言路由器对空回复干净降级、不崩溃、不 live**。**该图产出完整结构 Markdown 依赖网关速度修复/01 选型结论**，
  属已知待办（对齐 worker 5 合并后重录）。

## 4. 使用方法

```bash
# 离线全链（seed 缓存即 golden，CI 永不 live）
python3 -m pytest -q                # 92 passed, 2 skipped，无网络

# 实时（需 OPENCODE_API_KEY；env 或仓库根 .env，不从库）
python3 -m graph2note.cli parse test-images/02-digitize-pipeline.jpg -o out.md \
  --model glm-5.3-flash --cache-dir /tmp/g2n-cache --out-dir /tmp/g2n-out --no-preprocess
# 输出：out.md、/tmp/g2n-out/{assets,preprocessed,timing.json}；stdout 打印 JSON 摘要
python3 -m graph2note.cli examples/note.ir.json -o out.md   # 旧 IR->MD 入口不变
```

## 5. 已知待办 / 风险

- 网关速度修复合并（worker 5 `dev/gateway-speed-fix` → main）后，重录 01 空回复 golden 为有效 IR；
  核对 reasoning_tokens 字段网关是否回传（当前 None）。
- 预处理器对「深色纸/弱对比/手写体」的定标基于合成图；真实手写扫描需随 issue 01 数据集做更广验证。
- `missing_attachments` 断言已用于 02 全链（附件引用均有文件）。06 Web UI 打包可直接复用。
- 09 接解析（PDF 拆分 → 复用 `parse_document` + Router 扩展缝）；10 接 `verify_second_model`；11 接计时 JSON 基线 + `candidate_models`。

## 6. 验收对照

- [x] CLI `parse <image> -o <out.md>` 一条命令全链；`test-images/02` 产出结构正确 Markdown（离线 golden 全链断言）。
- [x] 横拍/旋转自动转正、歪斜透视校正输出优于未校正（合成图定标测试）。
- [x] 非法 IR 重试，最终失败明确错误（`RecognitionError`→CLI 退出码 1）而非崩溃。
- [x] 明确划掉/空内容降级路径（空 IR 不崩溃；语义化删除由系统 prompt 约束）。
- [x] golden-file 测试覆盖路由入口与 IR 校验，CI 无 live 调用。
