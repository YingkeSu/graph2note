# T-audit — 视觉基线审计 + 复验(brief)

Status: dispatched
分支:`audit/visual-diagram`(只读实现代码;唯一允许的提交是本目录 `reports/` 下的报告文档)
共享契约:[SPEC.md §1](../SPEC.md)。

## 使命

你是 D 轨的视觉测试者:用视觉模型(你本体的多模态能力,直接 Read 图片;另有远程 URL 图像分析 MCP 可选)找出当前结构图生成在人机交互与视觉上的问题,产出**基线问题清单**;D1/D2/D3 合并后再做**复验对比**,给出视觉 verdict。

## 两阶段

### 阶段 1(立即):基线审计 → `/tmp/spw-T-audit-baseline.md`

1. **读原图定标准**:Read `test-images/01-requirements-arch.jpg`、`02-digitize-pipeline.jpg`、`02-digitize-pipeline-increment.jpg`,逐图记录「手稿里人眼可见的结构意图」——层带/泳道/阶段/旁注/箭头语义。这是 ground truth,写进报告第一节。
2. **取现状产物**(全部离线、只读;逐项标注产物来源,拿不到的如实写「不可得」,严禁编造):
   - 仓库内现成渲染产物/IR:`examples/diagram-demo.ir.json`、`out/`(若你的 worktree 没有,可只读查看主检出 `/Users/suyingke/Programs/OHO/graph2note/out/` 与 `.cache`/缓存目录,**只许 ls/cat,禁止改写主检出任何文件**)。
   - 用现行确定性渲染器把能拿到的 IR 渲成 PNG(graphviz/matplotlib 渲染是离线确定性的,跑它们不算改代码;产物写 /tmp)。
   - 若环境有 API key 可跑一次 live VLM 抽取(通常没有;没有就跳过,不硬跑)。
3. **视觉问题清单**:对每张现状渲染,用视觉能力逐项检查并写明证据(截图+描述):层次缺失(节点挤平)、分组丢失、旁注混排、边交叉、字号/对比度可读性、中文标签截断/乱码、前端展示中的交互问题(若用 `PLAYWRIGHT_MODULE=/Users/suyingke/.npm/_npx/9833c18b2d85bc59/node_modules/playwright node scripts/frontend_audit.mjs` 巡检,**禁止** `find /Users/suyingke` 找依赖,会卡 15-20 分钟)。
4. **映射到 SPEC 验收锚点**:每条问题标注它对应 SPEC §1 哪条要求,以及复验时你将用什么判据判过/不过。
5. 报告落盘 `/tmp/spw-T-audit-baseline.md`,并把副本提交到自己分支的 `.scratch/structure-paper-weekly/reports/T-audit-baseline.md`(纯文档提交)。

### 阶段 2(等调度通知「D 轨已合并」):复验 → `/tmp/spw-T-audit-recheck.md`

- 在合并后的 main 上重跑同一取材流程,逐条对照基线问题清单:已解决/未解决/新引入。
- 对三张手稿图给出 SPEC 锚点逐项 verdict(01 层带、02 主线+旁注、02-increment),verdict: pass / fail(附证据截图)。
- 副本同样提交到自己分支 `reports/T-audit-recheck.md`。

## 纪律

- 不改任何实现代码;主检出只读;密钥不入产物;报告诚实标注产物来源与不可得项。
- 完成任一阶段 → `/tmp/spw-T-audit-{baseline,recheck}-done.md` 一行通知调度,然后停止等待。
- 卡住写 BLOCKED 段,不瞎猜。
