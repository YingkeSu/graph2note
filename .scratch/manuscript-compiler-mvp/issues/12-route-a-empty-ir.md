# Route A 产品管线在真实扫描页产出空 IR 的修复

Status: claimed

## Parent

[PRD](../PRD.md)（Route A 主链路质量）；证据链：issue 03（img01 golden 重录仍空正文，reasoning 烧 5000 token，gateway 不返回 reasoning_tokens）、issue 11 基线报告 §1/§7（产品管线在评估集扫描页渲染为空 IR，而 eval harness 的 Markdown 直转 prompt 可正常产出）。

## What to build

修复产品管线（`graph2note` parse → Route A IR-JSON prompt）在真实扫描页（板书/大图/密集页）上空 IR 的问题，使主链路在真实数据上可用。端到端行为：`test-images/01 + 评估集扫描页 → 非空、过 schema 校验的结构化 IR → 正常渲染 .md`。

- 根因定位：对比产品 prompt（IR-JSON 直出）与 eval harness prompt（Markdown 直转）在同一批页面的行为差异；量化空 IR 触发率（按页型分类）。
- 候选修复路径（按实测选择）：
  - 产品 prompt 对齐 eval harness 的有效策略（措辞/结构约束/示例）
  - 两阶段解析：VLM Markdown 直出 → 文本 LLM 结构化为 IR（网关文本模型清单见 docs/llm/opencode-go.md；注意 muse 系列禁用）
  - 直出约束强化 + session/token 预算调优（R1-R4 框架内）
- 质量门槛：评估集有 gold 的页面子集（≥5 页跨类目）产出非空合法 IR；与 gold 的 EditRate 有对比数据（联动 issue 01/11 顺延项）。

## Acceptance criteria

- [ ] 空 IR 触发率量化报告（修复前后，按页型分类）
- [ ] `test-images/01` 产出非空结构化 IR（golden 重录，替换现空 golden）
- [ ] 评估集 ≥5 页跨类目产出非空合法 IR 且 EditRate 有对比数据
- [ ] 修复不回退既有能力：`test-images/02` golden、全部离线测试保持绿
- [ ] 根因与修复决策记录进 handoff（供 08 Route B 设计参考）

## Blocked by

None - can start immediately（证据均在 main）
