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
| T-audit | 视觉基线审计 + 复验 | `audit/visual-diagram` | 只读源码；产物写 `reports/`（本目录）+ /tmp；不改实现代码 | 已派发 2026-09-14 |

D 轨共享契约：[SPEC.md §1 层次结构图 IR 扩展](SPEC.md)。D2/D3 针对 SPEC 契约与自建 fixture 开发，可在 `dev/D1-diagram-extract` 落盘后择机 rebase；合并顺序 D1 → D2 → D3，reviewer 负责集成验证。

## I 轨：issue 制（见 issues/）

| 编号 | Issue | 分支 | 开发者 | 状态 |
|---|---|---|---|---|
| P1 | [论文 PDF 导入管线](issues/P1-paper-pdf-ingest-pipeline.md) | `dev/P1-paper-ingest` | dev-A | 待派发（D 轨收官后串行启动） |
| P2 | [论文元数据与参考文献识别](issues/P2-paper-metadata-references.md) | `dev/P2-paper-meta` | dev-B | 待派发（D 轨收官后串行启动） |
| P3 | [论文阅读视图与库集成](issues/P3-paper-reading-view.md) | `dev/P3-paper-view` | dev-C | 待派发（D 轨收官后串行启动） |
| W1 | [周报内容结构与材料策略](issues/W1-digest-content-structure.md) | `dev/W1-digest-content` | dev-D | 待派发（D 轨收官后串行启动） |
| W2 | [周报展示交互与导出](issues/W2-digest-view-export.md) | `dev/W2-digest-view` | dev-D（W1 合并后接续） | 待派发（D 轨收官后串行启动） |

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
