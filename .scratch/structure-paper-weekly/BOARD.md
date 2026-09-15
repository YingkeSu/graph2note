# structure-paper-weekly 轮次看板（SPW）

Status: in-progress
启动：2026-09-14（维护者指令）；基线：main `a99aa37`（本地 main 领先 origin 19 提交，push 时机归维护者）。

## 目标（维护者原话拆解）

1. **优化结构流程图的生成**，特别是 test-images 三张手稿图（`01-requirements-arch.jpg`、`02-digitize-pipeline.jpg`、`02-digitize-pipeline-increment.jpg`）中的结构图——当前过于扁平、无层次、信息混乱。→ **D 轨（开放性优化）**
2. **增加论文导入模块**，针对论文识别读取做全线优化。→ **I 轨 issue P1–P3**
3. **优化周报模块**。→ **I 轨 issue W1–W2**

## 团队编制（维护者指定）

- D 轨（开放性）：3 worker（D1/D2/D3）+ 1 视觉测试者（T-audit）+ 2 reviewer（评审时 fresh spawn）。
- I 轨（issue 开发）：4 开发者（P1/P2/P3/W12）+ 2 reviewer（评审时 fresh spawn）。
- **两轨串行（维护者 2026-09-14 追加指令）：D 轨与 I 轨不可同时派发。先完成 D 轨（含合并与 T-audit 复验），再切 I 轨；切换时复用 D 轨 worker、微调任务派发，不整套换血。** 预设映射（届时按实际存活/表现调整）：D1→P1、D2→P2、D3→P3、T-audit→W1（→W2）；不足再补 spawn。
- 严禁 worker 自审；reviewer 每次 fresh spawn；reviewer 通过后由 reviewer 执行本地 main 合并 + 同步本 BOARD 状态（docs commit）；不 push origin。维护者已授权自主审批非安全问题（沿用前轮）。

## D 轨：结构流程图生成优化（brief 制，见 briefs/）

| 编号 | 任务 | 分支 | 领地 | 状态 |
|---|---|---|---|---|
| D1 | 层次化抽取与 IR 扩展 | `dev/D1-diagram-extract` | `graph2note/ir.py`（仅 diagram/flow 区块扩展）、`graph2note/diagram.py`、`graph2note/diagrams/infer.py`、对应新测试 | merged 2026-09-14 @ `b4d09d1`（reviewer 验收通过，全量 pytest 920 passed） |
| D2 | 分组感知布局引擎 | `dev/D2-diagram-layout` | `graph2note/diagrams/_layout.py`、`_canonical.py`、`engine.py`、对应新测试 | merged 2026-09-14 @ `4002288`（reviewer 验收通过，全量 pytest 980 passed） |
| D3 | 渲染与前端呈现 | `dev/D3-diagram-render` | `graph2note/diagrams/graphviz_renderer.py`、`matplotlib_renderer.py`、`degrade.py`、`graph2note/attachments.py`（DiagramSemantics）、`graph2note/render.py`（diagram 段）、webstatic 图展示组件、对应新测试 | merged 2026-09-14 @ `7b4a6b2`（reviewer 二轮验收通过，全量 pytest 1027 passed） |
| D4 | 阶段2复验缺陷整合修复（T-audit F-A/F-B/F-C/F-D/F-G/F-H + 字号三档） | `dev/D4-diagram-fix` | D3 渲染/字体 + D2 `_layout.py` + D1 `diagram.py`/`vlm.py`（三领地经调度授权）+ 对应既有测试 | merged 2026-09-15 @ `4c3782a`（fresh reviewer 全项自跑验收通过，全量 pytest 1037 passed） |
| D5a | 抽取 prompt 调优（note/dashed/防弱关联丢失，T-vision live §7-1/2/4；§7-3 设备归组不执行） | `dev/D5a-prompt-tune` | `graph2note/diagram.py` 的 `SYSTEM_PROMPT` 字符串 + `tests/test_diagram_groups_ir.py` | merged 2026-09-15 @ `5bcf431`（fresh reviewer 全项自跑：mutation 有牙、live 复现 note→01 / dashed→02inc(`label=参考`) / 02 关联保留为边、全量 pytest 1040 passed；残留 R1 截断 parse_fail、R2 02 参考未标 dashed） |
| D5b | mpl 密图原生重叠修复 + CJK 粗体 + N1 corner（T-vision live §2/§4/§7-5） | `dev/D5b-mpl-dense` | `graph2note/diagrams/matplotlib_renderer.py`（渲染/字体）+ `_layout.py`（经授权，仅 N1）+ 对应新测试 | merged 2026-09-15 @ `bf5a8ec`（fresh reviewer 全项自跑：live 21/10/32 节点 artist 相交 0/0/0（基线 24/1/45）、mutation 有牙、font_manager 警告 1→0、fuzz 400 例全符合 N1 模式且乱序 0 unstable、4 golden+anchor01/02/02inc 逐字段 == 基线、扁平 gv.dot/gv.png/mpl.png SHA256 逐字节同、全量 pytest 1046 passed；残留 F1：live02 单节点文字贴边 3px bbox / 1px ink，非 artist 相交） |
| D6 | mpl 组标题互压修复（T-vision final §3） | `dev/D6-grouptitle` | `graph2note/diagrams/matplotlib_renderer.py`（仅标题层）+ `tests/test_diagram_render_groups.py` | merged 2026-09-15 @ `6373328`（fresh reviewer 全项自跑：live 01/02/02inc 组标题文字∩文字 2/0/1→0/0/0，节点级五项 node∩node/文字越框/无唯一归属框/标题压节点框/边标签压框 0/0/0 不回退，组框∩组框 9/0/2 不变，只动标题层（figsize、全部 patch、非标题文字逐字段与基线同），4 golden+anchor01/02/02inc 逐字段 == 基线，扁平路径逐字节同，两新用例 main 红/分支绿且 `_assert_no_overlap` 第 5 项有牙，全量 pytest 1048 passed；残留：一行 3+ 同左界组滑移空间不足时回退历史锚点，best effort） |
| T-audit | 视觉基线审计 + 复验 | `audit/visual-diagram` | 只读源码；产物写 `reports/`（本目录）+ /tmp；不改实现代码 | 已派发 2026-09-14 |
| T-vision-final | D 轨四焦点最终视觉核验（D5 合并后收官 spot check） | 只读：`git archive 751ad9c` → /tmp（未建分支） | 只读源码；产物写 /tmp；不改实现代码 | 完成 2026-09-15（deepseek 抽取 5 次正式调用 + kimi 视觉判读 11 次）：**F-1 ✅**（01 notes=5，`坑：Tiger VNC 不支持`/`Critical Path 优化 ★` 进 note 不建并列节点）、**F-2 ✅形态**（01 dashed=5 含 `label=参考`×2、02inc dashed=3；02inc 本样本 `参考` 标签未落）、**F-3 ✅边形态**（02 `调研/确定`→`解析层` 关联保留为实线边，未标参考/dashed）、**F-4 ⚠️部分达成**（mpl 节点框 artist 相交 **0/0/0**，01=23 节点密图基线 32→0、文字越框 2→0、组标题压节点框 18/2/11→0；**残留**：组标题文字压叠 01=2 对 / 02inc=1 对（基线 4/1）、组框∩组框 01=9 / 02inc=2，VLM 在 02inc 顶带独立确认）。报告 `/tmp/spw-final-vision-report.md`。遗留指针：kimi 抽取通道长 prompt 空内容待裁决 / R1 半截 JSON 重试缺口 / F1 文字贴边残留（本轮未复现）/ 组标题压叠 / jsdelivr-marked 本地化与 D2 密图紧凑度记后续 |

D 轨共享契约：[SPEC.md §1 层次结构图 IR 扩展](SPEC.md)。D2/D3 针对 SPEC 契约与自建 fixture 开发，可在 `dev/D1-diagram-extract` 落盘后择机 rebase；合并顺序 D1 → D2 → D3，reviewer 负责集成验证。

## I 轨：issue 制（见 issues/）

| 编号 | Issue | 分支 | 开发者 | 状态 |
|---|---|---|---|---|
| P1 | [论文 PDF 导入管线](issues/P1-paper-pdf-ingest-pipeline.md) | `dev/P1-paper-ingest` | dev-A | merged 2026-09-15 @ `ec9b1d6`（fresh reviewer 全项自跑：领地零越界（webapp/store −0、pdflib 未改）、AC1–AC7 全达成、后端 mutation 有牙（去扫描回退 5 红 / 文本路径触发 LLM 4 红 / 破坏 paper.json 持久化 5 红）、合并后全量 pytest 1099 passed；残留 R1 upload.js PDF 拦截仅源码断言（守卫反转不红）、R2 handoff 报数 1096 陈旧） |
| P2 | [论文元数据与参考文献识别](issues/P2-paper-metadata-references.md) | `dev/P2-paper-meta` | dev-B | merged 2026-09-15 @ `adaff57`（fresh reviewer 全项自跑：领地零越界（webapp/store/taxonomy 删除行 0，papers/ 仅 P2 模块，未 import P1）、SPEC §2 契约逐项（单栏/双栏/arXiv 三排版字段级 + per-field provenance、参考文献定位/编号+作者-年份切分/跨栏 de-hyphenation/保守合并标注、citegraph DOI 优先+ambiguous 不假匹配+确定性、enhance forbid schema+只填空+注入 planner+无 key 降级不抛错）、4 项 mutation 全红（删 de-hyphenation / 放宽 forbid / 去 ambiguous 剔除 / 允许覆盖）、分支树全量 pytest 1088 passed、P1→P2 机械解冲突（__init__ 保 P1、store/webapp/taxonomy 保双方）后合并全量 1139 passed；残留 R1 PATCH `/metadata` 与 PUT 同为整体替换（部分 body 会清空其余字段，建议 P3 接线前修）、R2 P1 `model.py` 与 P2 各自定义同名 `PaperMeta/PaperReference` 待集成收敛、R3 硬连字符行尾拼接 best-effort、R4 `pyproject.toml` packages 未加 `graph2note.papers`、R5 handoff 报数 1087 陈旧） |
| P3 | [论文阅读视图与库集成](issues/P3-paper-reading-view.md) | `dev/P3-paper-view` | dev-C | merged 2026-09-15 @ `0d96dec`（R2 fresh reviewer 全项自跑：领地零越界（store.py/papers 零 diff，webapp +137/−0 纯追加，style.css +82/−0）、首轮两阻塞缺陷真修复——缺陷 A `_paper_view_payload` 改走 `store.get_paper_payload`(P1 sections/page_map)+`store.paper_payload`(P2 meta/references)、`_paper_blob`/`_paper_doc_kind` 已删，live 真实 P1 导入后 P3 sections 与 P1 payload 逐字段相同 9/9、`page_label` 与 `page_map` 独立重算一致（0-based→1-based）；缺陷 B P3 索引端点已删、`app.routes` 字面量 `GET /api/papers` 恰 1 条且返回 P1 job list（list, n=1），前端徽标改走 `/api/documents` 的 `doc_kind`；live 集成 32/32 PASS（零模型调用）；哨兵有牙——首轮代码 `24c7ef2`+main 换入新测试后 8 红（缺陷 A `[] == ['1 Introduction','1.1 Background']`、缺陷 B `{'papers':[],'count':0}` 非 list、`test_paper_import_text_layer_chain` 复现 `TypeError: string indices`），合并树全量 pytest 1202 passed、node 套件（paper_view/library_cards/router_routes 等 7 个 mjs）绿；脏文件 md5 保持不变、密钥扫描零命中；残留 R1 落点收敛（P1 `paper.json` vs P2 `record.json.paper`）留 P1/P2 后续、R2 `#doc` 分发依赖 document.js 先于 paper.js 注册） |
| W1 | [周报内容结构与材料策略](issues/W1-digest-content-structure.md) | `dev/W1-digest-content` | dev-D | merged 2026-09-15 @ `e601341`（fresh reviewer 全项自跑：领地干净（webapp/telemetry/ir/diagram/papers/webstatic/store 零 diff，digest.py 独占，taxonomy 仅 +2 行，test_weekly_digest 仅 1 用例改名扩展无既有 AC 删除）、六项核心声明自跑（5 类模型输出的四节骨架/纯散文与坏 JSON 回退仍四节、text 通道抛异常下统计照常、未知 document id 丢弃不伪造、节级指纹版本号变正文不变零调用 + GENERATOR_VERSION 进整报指纹 + force 重生成、预算纯函数时间优先+主题保底+报告进 meta、旧 meta 无 sections 不炸）、mutation A 删四节常量 / B 放宽 schema / D 忽略 topic floor / E 摘录越界均红、全量 pytest 1096 passed、node 套件绿；合并前 main 已含 P1+P2，merge-tree 无冲突，合并后全量 pytest 1187 passed；残留 R7 `GENERATOR_VERSION` 进指纹无回归测试（功能正确，mutation C 仍绿）、R8 裁剪时 `stats.document_count`(范围内总数) 与 `meta.document_count`(选入数) 同名异义、概览 source ids 含被裁剪文档） |
| W2 | [周报展示交互与导出](issues/W2-digest-view-export.md) | `dev/W2-digest-view` | dev-D（W1 合并后接续） | merged 2026-09-15 @ `fbd216c`（fresh reviewer 全项自跑：领地干净（`digest.py`/`webapp.py`/`index.html`/`api.js`/`state.js`/`router.js` 零 diff，仅 dashboard.js 周报块 + style.css 末尾 57 行纯追加 + 新前端测试 + taxonomy +1；未新增 API 端点，导出为前端 Blob）、六项验收自跑（分节渲染+旧 meta 整篇回退、活 id `<a href="#doc/<id>">` 跳转/失效 id 灰显 button+toast 不炸、Blob 导出 `weekly-digest_<from>_<to>_<created>.md`、历史空/生成中/失败三态可操作按钮+`aria-busy`/`aria-current`、对比度真实库 5.83/合成 fixture 5.52 + `frontend_audit.mjs` 3 宽度 33 checks 0 findings + 390px 无溢出、离线 node DOM 契约套件绿）、**真实 W1 数据端到端**（主仓 .env 通道 provider=kimi model=kimi-k3，43 篇真实库 POST /api/digests → status=ok llm_calls=1 llm_mode=json；meta.sections keys 顺序/形状与 W1 契约一致、POST 扁平==GET meta.sections、91 条来源引用去重 43 id 全部命中真实库、stats.document_count=43==meta.document_count、前端 91 chips 全真实 id+标题且点击真跳 `#doc/doc-00`、统计条逐项匹配、导出文件名/内容四节正确；密钥未打印未导出，服务进程已回收）、mutation 4 项全红（强制整篇回退/失效 id 改回 `<a>`/导出文件名去日期/`.digest-source` 色改 `#1f6feb`→对比度 4.11<4.5）、合并 P3 后 style.css 双追加冲突按「P3 块 + W2 块」纯追加解冲突（prefix 与 P3 HEAD 逐字节一致、W2 块与作者版逐字节一致），合并后全量 pytest **1207 passed**；脏文件 md5 `cb5bdf8626fb9cff52f692de0daf5ebb` 未变、密钥扫描零命中；残留 R1 库索引仅面板进入时刷新、R2 来源 chips 多时仅换行、R3 `## 来源` extras 块与节内 chips 并存、R4 旧 meta 导出 range 缺失用 `unknown`、R6 `historyFailed` 仅 node 覆盖、失效 chip 对比度仅合成 fixture live 覆盖） |

I 轨共享契约：[SPEC.md §2 论文文档契约](SPEC.md)。P2/P3 针对契约 + fixture 并行开发，不 import P1 未合并代码；合并顺序 P1 → P2 → P3、W1 → W2。

## 领地与共享文件纪律

- 新代码优先进新文件/新包（`graph2note/papers/`），避免跨轨碰撞。
- 共享文件**只追加、不改既有行**：`graph2note/webapp.py`（P1/P2/P3/W12 各自追加独立路由段，P1/P2 用 `/api/papers/*` 前缀，W12 在 `/api/digests/*` 既有段内追加）、`graph2note/store.py`（确需扩展时只追加新方法）、`webstatic/index.html`（P3 独占导航/容器追加；W12 原则上不动）、`webstatic/js/router.js`、`api.js`、`state.js`（P3 追加注册，保持最小）。
- D 轨三 worker 领地互不相交（见上表）；`ir.py` 仅 D1 可动。
- 密钥/.env 不入任何产物与提交；worker 环境通常无 API key → 一律离线 golden/fixture 测试，live 验证缺失须在 handoff 诚实标注（沿用前轮零预算说明）。

## 流程（沿用 4+2 协议）

1. worker 完成 → 写 handoff（`handoffs/<编号>-<slug>.md`，标注 ready-for-review）+ 最终汇报写 `/tmp/spw-<编号>-done-report.md`（调度读不到会话回复）。
2. 调度核验分支与 handoff 落盘 → kill worker → fresh spawn reviewer（verdict 写 `/tmp/review-spw-<编号>-verdict.md`；≤2 并发）。
3. reviewer 通过 → 合并入本地 main + 更新本 BOARD/issue 状态（docs commit）；打回 → 修复后由**不同会话**重审。
4. 全部合并后向维护者收官汇报 + push 时机提醒。

## 操作教训（前轮实证，写入所有 prompt）

- **禁止 `find /Users/suyingke` 等爬盘命令**（单次 15–20 分钟阻塞会话）。前端巡检用 `PLAYWRIGHT_MODULE=/Users/suyingke/.npm/_npx/9833c18b2d85bc59/node_modules/playwright node scripts/frontend_audit.mjs`（备用缓存 `e41f203b7505f1fb`）。
- 慢工具阻塞 ≠ 冻结；会话卡死先查前台进程。
- 每页/每逻辑单元一个提交，便于抢救与重放。

## 后续 issue 索引（SPW 双轨评审与终检遗留）

从 D 轨（X1–X6）与 I 轨（Y1–Y6）的评审 verdict 与终检报告中整理的后续 issue；均为 `Status: ready`，文件在 `issues/`。来源：D 轨 `/tmp/spw-final-vision-report.md`、`/tmp/review-spw-D3fix-verdict.md`、`/tmp/review-spw-D5a-verdict.md`、`/tmp/review-spw-D5b-verdict.md`、`/tmp/spw-D5a-done-report.md`；I 轨 `/tmp/review-spw-P1-verdict.md`、`/tmp/review-spw-P2-verdict.md`、`/tmp/review-spw-P3-r2-verdict.md`、`/tmp/review-spw-W2-verdict.md`、`/tmp/spw-P1-done-report.md`、`/tmp/spw-W1-done-report.md`。

| 编号 | 一句话 | 文件 |
|---|---|---|
| X1 | kimi diagram 抽取通道长 prompt 下 3/3 空内容（deepseek 3/3 ok），待裁决通道/预算/prompt | [X1-kimi-extract-channel.md](issues/X1-kimi-extract-channel.md) |
| X2 | 抽取重试缺口：半截 JSON（length + 非空 parse_fail）不触发预算升级重试 | [X2-extract-retry-partial-json.md](issues/X2-extract-retry-partial-json.md) |
| X3 | mpl 组框相交（01 图 9 对、02inc 2 对），lane×cluster 布局语义层 | [X3-mpl-group-box-intersection.md](issues/X3-mpl-group-box-intersection.md) |
| X4 | mpl 字宽启发式「1 unit = 半 em」低估中英混排约 12%，文字越自身框 | [X4-mpl-text-width-heuristic.md](issues/X4-mpl-text-width-heuristic.md) |
| X5 | marked.js 的 jsdelivr CDN 依赖本地化（离线可用性） | [X5-marked-cdn-localize.md](issues/X5-marked-cdn-localize.md) |
| X6 | D2 密图默认文档视图紧凑度（放大镜链路已救，默认视图不可读） | [X6-dense-diagram-default-view.md](issues/X6-dense-diagram-default-view.md) |
| Y1 | PATCH /api/papers/{id}/metadata 与 PUT 同为整体替换，静默清字段 | [Y1-patch-put-metadata-replace.md](issues/Y1-patch-put-metadata-replace.md) |
| Y2 | P1 paper.json 与 P2 record.json.paper 双落点收敛（可选；消费者侧已化解） | [Y2-paper-json-record-json-convergence.md](issues/Y2-paper-json-record-json-convergence.md) |
| Y3 | upload.js PDF 拦截缺行为级测试（守卫反转不红） | [Y3-upload-pdf-intercept-test.md](issues/Y3-upload-pdf-intercept-test.md) |
| Y4 | 真实论文样本回归验证（P1 全合成 fixture） | [Y4-real-paper-fixtures.md](issues/Y4-real-paper-fixtures.md) |
| Y5 | P2 作者切分把摘要并入 authors（合成 PDF 回流文本） | [Y5-author-split-abstract.md](issues/Y5-author-split-abstract.md) |
| Y6 | W1 周报遗留 R1–R5 汇总（连续体对≈0 / inbox 口径 / meta 体积 / 长材料 JSON 稳定性 / llm_calls=0 的 elapsed） | [Y6-w1-digest-leftovers.md](issues/Y6-w1-digest-leftovers.md) |

## X/Y 轮执行状态（2026-09-15 起，用户指令「根据最新的issue反馈，继续更新优化」）

维护者裁决（2026-09-15）：X1 → (a) diagram 默认通道切 deepseek 视觉；X6 → 优化默认视图设计使密图可读（不做放大引导绕行）；Y2 → (b) 保持双落点 + SPEC §2 契约化。

| 编号 | 状态 | 分支 / 合并 | 备注 |
|---|---|---|---|
| Y1 | ✅ merged `f8c6f61`（rev-112 APPROVE，verdict `/tmp/review-spw-Y1-verdict.md`） | `dev/Y1-patch-metadata` @ `5984a5a` | PATCH 部分合并 / PUT 整体替换；1211 passed；残留：documents metadata 同问题另立项 |
| X2 | ✅ merged `55c8c15`（rev-113 APPROVE，verdict `/tmp/review-spw-X2-verdict.md`） | `dev/X2-extract-retry` @ `81b9ad3` | 半截 JSON 升级重试四分支；1214 passed |
| X5 | ✅ merged `2eb5fed`（rev-114 APPROVE，verdict `/tmp/review-spw-X5-verdict.md`） | `dev/X5-marked-localize` @ `270580f` | marked 4.3.0 本地 vendor，离线探针 10/10 |
| Y5 | R2 重审中（rev-123，与 R1 reviewer 不同会话） | `dev/Y5-author-split` @ `d88fac5` | D1 修复：kept 守卫 + hint 区分大小写；+4 回归用例；6 组 mutation |
| X1 | ✅ merged `f0dd99e`（rev-121 APPROVE，verdict `/tmp/review-spw-X1-verdict.md`） | `dev/X1-deepseek-channel` @ `09a7a9e` | live 3/3 ok；02inc 触发 X2 重试联动验证；其他 purpose 不回归 |
| X3+X4 | 评审中（rev-124） | `dev/X3X4-mpl-layout` @ `b74f0cc` | 组框相交 9/0/2→0/0/0；字宽真实 metrics 越框清零；golden/扁平逐字节不动；1224 passed |
| Y3 | ✅ merged `875fbde`（rev-120 APPROVE，verdict `/tmp/review-spw-Y3-verdict.md`） | `dev/Y3-upload-test` @ `26a804f` | upload.js 拦截行为测试；1219 passed |
| Y4 | 已交付，评审暂缓：**Blocked by Y5-r2**（fixture 是 P2 行为快照，分支本地并入了被 REJECT 的 Y5 基线，须待 Y5-r2 合并后 rebase 再审） | `dev/Y4-real-fixtures` @ `b420df3` | 4 真实论文 67 新例 1292 passed；发现 5 个新 issue 候选（噪声标题/标题吞 byline/authors 混机构/DOI 来源/参考文献欠切分） |
| X6 | 待派（待 X3X4 合并，共享 renderer/_layout） | — | 裁决：优化默认视图设计使密图可读 |
| Y6 | 已交付，待评审空位 | `dev/Y6-digest-leftovers` @ `52cea75` | R1-R5+R7/R8 全关闭；+15 例；mutation 6/6 红；1239 passed |
| Y2 | 实现中（worker-125；Y6 最终未碰 store/webapp，无冲突故提前） | `dev/Y2-dualslot-contract` | 裁决 (b)：双落点契约化 + 不变量测试 |

BOARD 行由调度统一登记（前轮并发 reviewer 撞 BOARD 教训）；reviewer 只合代码不碰本文件。
