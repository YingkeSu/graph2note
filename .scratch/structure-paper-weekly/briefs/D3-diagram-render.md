# D3 — 渲染与前端呈现(brief)

Status: dispatched
分支:`dev/D3-diagram-render`(基线:本地 main)
共享契约:[SPEC.md §1](../SPEC.md)。

## 使命

把分组/旁注/弱关联画出来:graphviz 用 `cluster_*` 子图,matplotlib 回退画分组背景框+组标题;node.note 以小一号字渲染在标签下方;group label 字号 ≥ note 字号;dashed 边;前端文档视图中结构图呈现层次可读。

## 领地(越界即打回)

- 独占:`graph2note/diagrams/graphviz_renderer.py`、`matplotlib_renderer.py`、`degrade.py`、`graph2note/attachments.py`(仅 DiagramSemantics 段)、`graph2note/render.py`(仅 diagram 段)、webstatic 图展示组件(`assets.js` 与 `views/document.js` 中 diagram 呈现段、`style.css` 图表相关**只追加**)、新增测试文件。
- 禁改:`ir.py`/`diagram.py`/`infer.py`(D1)、`_layout.py`/`_canonical.py`/`engine.py`(D2)、`index.html`、`router.js`、`api.js`、`state.js`(I 轨领地)、`digest.py`、`webapp.py`、`store.py`。

## 与 D1/D2 的并行解耦(关键)

- renderer 入参以 **SPEC §1 JSON 形状**(dict)开发,不 import D1 未合并模型、不依赖 D2 未合并几何:分组绘制所需几何(成员包络框)允许你在本分支写临时推导,并留 TODO 注明「D2 合并后替换为其 engine 输出」。
- 收到调度「D1/D2 已合并」通知后 rebase 接线并跑全量测试,handoff 补记。合并顺序 D1→D2→D3,你是最后一个,集成风险最高——提交粒度细一些。

## 任务清单

1. graphviz renderer:kind=layer/lane/cluster → `cluster_*` 子图(或等价 rank 约束);组标题;note 小字;dashed 边;中文字体沿用现行处理。
2. matplotlib 回退:分组背景框 + 组标题;同字号规则;无 groups 时输出与现行 golden 一致(回归锁定)。
3. `degrade.py`(crop&embed 路径):确认与新语义不冲突——降级产物是源图裁剪嵌入,不涉分组;只做必要的兼容断言。
4. `attachments.py` DiagramSemantics + `render.py` diagram 段:groups/note/style 能流经导出链(如 Markdown 导出中的 diagram 块描述)而不丢信息;导出格式在 handoff 说明。
5. 前端:文档视图里结构图(渲染产物/SVG/图片)展示层次可读——核对现有展示路径(assets.js、views/document.js),必要时调整展示容器/说明文字;**只追加式**动 style.css;不动路由与其他视图。
6. 测试:renderer golden(有/无 groups)、字号规则断言、导出链不丢字段;前端改动用 `PLAYWRIGHT_MODULE=/Users/suyingke/.npm/_npx/9833c18b2d85bc59/node_modules/playwright node scripts/frontend_audit.mjs` 巡检(备用缓存 `e41f203b7505f1fb`;**禁止** `find /Users/suyingke` 找 playwright,会卡 15-20 分钟)。

## 验收锚点

- SPEC §1「渲染」条 + 三张手稿图锚点(T-audit 复验):01 三层带可视、02 主线+旁注分层可视。

## 流程与纪律(必守)

- 先读:[BOARD.md](../BOARD.md)、[SPEC.md](../SPEC.md)、本 brief、`AGENTS.md`。
- 每逻辑单元一提交;不 push origin;不合并自己;不自审;密钥不入产物。
- 完成 → `handoffs/D3-diagram-render.md`(**ready-for-review**:改动清单、渲染效果证据(golden 输出路径/截图)、rebase 状态、测试证据、诚实限制)+ `/tmp/spw-D3-done-report.md`,然后停止等待调度。
- 卡住写 BLOCKED,不瞎猜。
