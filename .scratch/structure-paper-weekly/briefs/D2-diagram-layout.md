# D2 — 分组感知布局引擎(brief)

Status: dispatched
分支:`dev/D2-diagram-layout`(基线:本地 main)
共享契约:[SPEC.md §1](../SPEC.md)。

## 使命

布局从「最长路径分层」升级为「分组感知分层」:同 layer 成员优先同水平带、同 lane 成员优先同垂直列、cluster 就近成簇;层带顺序由确定性推导(自上而下阅读序);同一语义输入字节一致输出。

## 领地(越界即打回)

- 独占:`graph2note/diagrams/_layout.py`、`_canonical.py`、`engine.py`、新增测试文件(如 `tests/test_diagram_group_layout.py`)。
- 禁改:`ir.py`、`diagram.py`、`infer.py`(D1 领地)、renderer/`degrade.py`/`attachments.py`/`render.py`/webstatic(D3)、其余全部。

## 与 D1 的并行解耦(关键)

D1 正在并行扩展 `ir.py`,你**不能 import 也不需要 import** 他的未合并代码:

- 布局函数以 **SPEC §1 的 JSON 形状**为输入契约(纯 dict 或本文件内自定义的轻量类型别名),自建带 groups 的 fixture 开发测试。
- `_canonical.py` 的 groups 规范化(按 id 排序、成员排序)同样按 SPEC 形状实现;D1 合并后由 reviewer/调度安排 rebase 接线(把 dict 入参换成 pydantic 模型序列化结果,预期零逻辑改动)。
- rebase 接线是你的收尾职责之一:收到调度通知「D1 已合并」后,`git rebase` 到新 main 并跑全量测试,在 handoff 补记 rebase 结果。

## 任务清单

1. 分组感知分层算法:layer(水平带,跨图整行)/lane(垂直泳道)/cluster(局部簇)三种 kind 的排布规则;无 groups 输入时行为与现行完全一致(回归锁定)。
2. 层序确定性:不允许 order 字段参与;顺序由布局从图结构+组标签规范推导。若认定必须保留 VLM 层序,可在 SPEC 允许范围内提议 `order_hint`,handoff 记录理由(默认不做)。
3. 交叉减少:同组成员排布应减少边交叉(启发式即可,确定性优先于最优性)。
4. `_canonical.py`:groups 规范化 + 现有规范化不动;同一语义字节一致(FR-020 延续),固化 golden 测试。
5. `engine.py`:把分组信息接入渲染管线的数据准备(给 D3 的 renderer 传递分组几何/分组元数据;几何计算在你,绘制在 D3——接口在 handoff 写清楚)。
6. 测试:三种 kind 各至少 1 个 golden fixture;确定性(同输入两次运行字节一致);无 groups 回归;节点数 0/1、空组、单节点组等边界。

## 验收锚点

- SPEC §1「布局」条 + 三张手稿图锚点(由 T-audit 按 SPEC 复验;你的 fixture 应覆盖锚点同构场景:三层带、管线+旁注)。

## 流程与纪律(必守)

- 先读:[BOARD.md](../BOARD.md)、[SPEC.md](../SPEC.md)、本 brief、`AGENTS.md`。
- 每逻辑单元一提交;禁爬盘命令(见 BOARD 操作教训);不 push origin;不合并自己;不自审;密钥不入产物。
- 完成 → `handoffs/D2-diagram-layout.md`(**ready-for-review**:改动清单、布局规则说明、与 D3 的接口说明、rebase 状态、测试证据、诚实限制)+ `/tmp/spw-D2-done-report.md`,然后停止等待调度。
- 卡住写 BLOCKED,不瞎猜。
