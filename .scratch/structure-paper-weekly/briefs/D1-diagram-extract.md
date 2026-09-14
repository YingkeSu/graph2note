# D1 — 层次化抽取与 IR 扩展(brief)

Status: dispatched
分支:`dev/D1-diagram-extract`(基线:本地 main,勿基于其他 dev 分支)
共享契约:[SPEC.md §1](../SPEC.md)——数据形状以 SPEC 为准,实现可超出不可违反。

## 使命

让「图 → 结构」这条线能表达层次:IR 支持视觉分组(groups)、节点旁注(note)、弱关联边(dashed);VLM 抽取契约升级为「先识别页面中的分层/泳道结构,再填节点与边;主标签与旁注分流」。

## 领地(越界即打回)

- 独占:`graph2note/ir.py`(**仅** diagram/flow 区块扩展)、`graph2note/diagram.py`、`graph2note/diagrams/infer.py`、新增测试文件(独立命名,如 `tests/test_diagram_groups_ir.py`)。
- 禁改:`_layout.py`/`_canonical.py`/`engine.py`/两个 renderer/`degrade.py`/`attachments.py`/`render.py`/webstatic 全部(D2/D3 领地)、`digest.py`、`webapp.py`、`store.py`。

## 任务清单

1. IR 扩展(SPEC §1 原文):`DiagramGroup(id,label,kind,nodes)`、`Node.note`、`Edge.style`、`DiagramBlock/FlowBlock.groups`。全部可选、缺省即现行行为;悬空组员引用校验拒绝;`extra` 拒绝策略不变;旧 IR JSON 双向兼容(缺省字段序列化省略或显式空,二选一,handoff 说明理由)。
2. `_canonical` 之外的确定性:你负责的抽取侧输出若有序集合,排序规则写死并测试(为 D2 的规范化铺路)。
3. `diagram.py` VLM 契约升级:SYSTEM_PROMPT 升级为输出可选 `groups`/`note`/`style` 的严格 JSON;**无层次可识别时合法输出空 groups,严禁编造层次**;`validate_diagram_json` 相应扩展(组员 id 必须存在、kind 枚举校验);预算升级重试/空内容降级语义不变。
4. `diagrams/infer.py`:若它从 Markdown/文本侧推断图,同样支持 groups 语义(能力所及范围内;做不到的在 handoff 标注)。
5. 测试:pydantic 兼容性(旧 JSON 加载/新 JSON 回读)、校验拒绝用例(悬空引用、坏 kind、自环保持)、prompt 契约(stub 掉 HTTP 层,断言新 prompt 文本与解析路径)、`python -m pytest` 全量绿。

## 验收锚点(SPEC §1 原文,T-audit 将按此复验)

- 01-requirements-arch:≥2 个水平层带,macmini/macbook/windows laptop 归入对应层;右侧通信方案文字区不混入图节点(或作 note/独立块)。
- 02-digitize-pipeline:阶段主线清晰主流向;旁注(如「critical path 优化 ☆」)以 note/虚线呈现,不与主流程节点同级混排。
- 离线环境下你无法跑 live VLM——用 stub/fixture 证明契约正确即可,handoff 诚实标注「live 未跑」。

## 流程与纪律(必守)

- 先读:[BOARD.md](../BOARD.md)、[SPEC.md](../SPEC.md)、本 brief、`AGENTS.md`。
- 每逻辑单元一个提交,信息用英文 conventional 风格(沿用仓库惯例)。
- 禁止 `find /Users/suyingke`、`grep -r /Users/suyingke` 等爬盘命令(会卡死 15-20 分钟)。需要 Playwright 时用 `PLAYWRIGHT_MODULE=/Users/suyingke/.npm/_npx/9833c18b2d85bc59/node_modules/playwright node scripts/frontend_audit.mjs`(本任务大概率用不到)。
- 不 push origin;不合并自己的分支;不自审;密钥/.env 不入任何产物。
- 完成 → 写 `handoffs/D1-diagram-extract.md`(标注 **ready-for-review**,含:改动清单、决策记录、测试证据、诚实限制)+ 最终汇报写 `/tmp/spw-D1-done-report.md`(调度读不到会话回复,以文件为准),然后停止等待调度。
- 卡住/有歧义:在 handoff 起头写 BLOCKED 段 + /tmp 报告,不要瞎猜硬做。
