# 阶段性总结：Manuscript Compiler MVP + notes-organizer（2026-09-08 ~ 09-09）

> 由调度 agent（dispatcher）维护。本文是第一阶段（MVP 主链 + P1 增补 + notes-organizer）的整合总结。
> 运行基线：main `f11adc6`，**295 passed + 2 skipped（全离线）**，99 commits，已推送 origin。

## 1. 一句话结论

手写/扫描手稿 → 结构化 Markdown 的本地全链路平台已可用（CLI + Web 三栏 UI），架构/流程图重建链路端到端打通，双功能 feature 共 **20 个 issue 全部 merged**；选型定案 **glm-5.3-flash**（Route A 主模型）；单页解析 **P95 ≈ 6.4s**（预算 60s）。

## 2. 交付清单（20/20 merged）

| # | Issue | 交付要点 | commit |
|---|---|---|---|
| 02 | IR schema + 确定性渲染器 | pydantic 中心契约（10 block 类型）、纯函数渲染、附件 seam、CLI | 2a06952 |
| 01 | Spike 1 评估 harness + 全量评估 | EditRate 指标、30 页六类评估集、双模型对比报告、gold 复核 PDF 合集 | f50a414/9ece166/4c67958 |
| 04 | Spike 3 图形重建可行性 | VLM 提取 nodes/edges ~83% 成功；graphviz 主/matplotlib 回退；降级裁图 | bb28a01 |
| 05 | Diagram 渲染 + 附件 | AttachmentWriter 真实实现、逐字节确定性、附件完整性检查 | 9593366 |
| 03 | 解析链路 CLI | 预处理（转正/透视/裁剪/对比度）→ Router → VLM → IR → .md；分阶段计时 | 4c0cb1e |
| 06 | Web App 三栏 | 上传→三栏（原图|可编辑 MD|KaTeX 实时预览）→复制/导出 | ddf3dba |
| 07 | 本机文档库 | FileDocumentStore 持久化、列表/打开/删除、版本机制 | 6ee8cad |
| 08 | Spike 2 / Route B | tesseract+LLM 对比：**Route A 全面占优**（0.768 vs 0.865）；清印刷窄域切 B 策略 | b46561f |
| 09 | PDF 拆页+去重+缺页预警 | PyMuPDF 拆页、pHash 聚类（可调阈值可拆分）、best-effort 缺页线索 | d5df80f |
| 10 | 交叉验证引擎 | 双模型 3 类块级 diff + 近重复 + 单模型「未验证」降级 | da3fead |
| 11 | 解析提速 | 网关收敛、结果缓存（重解析零调用）、多页并发；P95 6.4s | 3f57669 |
| 12 | Route A 空 IR 修复 | 两阶段解析（VLM→Markdown→确定性 IR）；6/6 扫描页非空 | 2227dd3 |
| 13 | Ingest↔Store 去重集成 | 同页多次扫描并入 DocumentRecord 候选版本（默认最新可拆分） | 89e2b6e |
| 14 | 网关会话隔离 | parse/eval/verify 独立已验证直出 session + 直出探针 | a6e9222 |
| 15/15b | 图形提取入管线 + CLI 修复 | 文本关系推断 + 视觉提取器产品化；`-o` 资产同址 | bfeb9a9/e1e39dd |
| 06b/06c | 预览资产重写 + marked 锁版本 | 三栏预览可见重建图（marked@4.3.0 锁定+双签名兼容） | 0b63e1d→f5c1bfc、0b63e1d 链 |
| NO-01/02/03 | Obsidian vault 导出/分类 MOC/增量导出 | 溯源 frontmatter、死链校验、幂等、指纹增量 | 2c4be9c/32723b7/f18e07e |

## 3. 架构一览

```
上传（JPG/PNG ≤10MB / 扫描 PDF 拆页）
  → 预处理（EXIF+内容转正 / 透视 / 裁剪 / 对比度；~0.4s/页）
  → RecognitionRouter（Route A=VLM 直出；Route B=OCR+文本 LLM 窄域备用；verify_second_model 缝）
      · 两阶段：VLM→非空 Markdown（token 升级+硬超时+策略切换）→ 确定性 Markdown→IR
      · 图形提取：文本侧 A→B 关系推断 + 视觉 nodes/edges 提取器（diagram.py，opt-in）
  → Document IR（pydantic 强校验；diagram/flow 携带 nodes/edges；非法拒入渲染）
  → 确定性渲染（Markdown / 重建图 PNG assets；graphviz 主 + matplotlib 回退；降级裁原图）
  → 三栏 Web（原图|可编辑 MD|KaTeX 预览）+ 本机文档库（FileDocumentStore）
  → 复制 / 导出 .md+assets zip / Obsidian vault（溯源+MOC+增量）
```

模块地图：`graph2note/`（ir/render/attachments/diagrams/preprocess/router/vlm/pipeline/timing/store/webapp/ingest/verify/notes/ocr/route_b/cli）+ `eval/`（harness/gateway/报告）+ `spike3/`（证据存档）+ `scripts/validate_sessions.py`。

## 4. 质量与性能证据

- **测试**：295 passed + 2 skipped（全离线；graphviz/PyMuPDF 可选依赖干净 skip）
- **确定性（FR-006/020）**：同一 IR 渲染、同一 diagram 重建、同一导出，均逐字节一致（回归覆盖）
- **性能**：单页端到端 P95 ≈ 6.4s（预算 60s）；预处理 0.4s；重解析零调用（结果缓存）
- **选型**（30 页、六类、双模型、生产配置口径）：glm-5.3-flash 30/30 成功、EditRate 0.768、延迟均值 40s；deepseek 23/30、0.840、80s、reasoning 均值 4648 → **定案 glm-5.3-flash**
- **EditRate 口径注意**：字符级 diff 把 Markdown 标记/空行差异计入，绝对值（~0.77）偏高且 gold 为 AI 草拟——维护者通览后临时验收，精细校对可增量进行

## 5. 关键决策记录

1. **中心契约**：Document IR 是解析唯一合法产物、渲染唯一合法输入；新增输出=新增 renderer（FR 契约不动）
2. **两阶段解析**（issue 12）：单阶段 IR-JSON prompt 在密集扫描页产空 IR；改为 VLM→Markdown→确定性结构化，空 IR 根因消除
3. **路由策略**（issue 08）：默认恒走 Route A；仅「清印刷+纯文本且 OCR 置信度≥55」切 B；AutoRouter 实现但非默认（待真实印刷证据）
4. **会话隔离**（issue 14）：共享 session 并发争用导致退化短补全——按用途隔离+直出探针+健康巡检（`--check` 非零退出可作门禁）
5. **marked 锁版本**（issue 06c）：CDN 未锁版本致 renderer 签名漂移、重写静默失效——锁 4.3.0+双签名兼容
6. **平台定位**：个人自用本地部署（单用户/无鉴权/仅本机），数据保留至用户删除

## 6. 缺陷复盘（验收/实测抓到并修复）

| 缺陷 | 根因 | 修复 |
|---|---|---|
| 架构图输出纯文本（维护者 UI 实测） | 两阶段把图形扁平化；视觉提取未接线 | issue 15 端到端闭环 |
| CLI `-o` 死链 | out-dir 默认图片父目录 | 15b 资产同址 |
| 预览不显示重建图 | 前端无 assets 路径重写 | 06b |
| 06b 修复运行时不生效 | marked CDN 未锁版本，renderer 签名漂移 | 06c 锁版本+双签名 |
| 偶发 300s+ 空正文 | 新 session 路由推理变体思考狂暴 | 诊断报告→R1-R4 落地 |
| 同名上传合并为同一文档 | doc_id 用了常量文件名 | 07 内修复 |

## 7. 运行指南

```bash
# Web UI（推荐）
python3 -m uvicorn graph2note.webapp:create_app --factory --host 127.0.0.1 --port 8734
# CLI 单页解析
python3 -m graph2note.cli parse <image> -o out.md
# 评估 harness / gold 复核 PDF
python3 -m eval.gold_review --pdf
# PDF 批量入库 / 交叉验证 / vault 导出
# （ingest pdf 子命令 / graph2note verify / graph2note notes-export，详见各 handoff）
```
密钥：本机 `.env`（OPENCODE_API_KEY），已 gitignore，任何代码/文档不含密钥。

## 8. 开放事项（下一阶段候选，未立项）

1. **EditRate 质量迭代**：结构感知 diff 指标 + prompt 精调（gold 可增量精修后基线更准）
2. **印刷类样本**：补真实打印页 → 复验 Route B 窄域 → AutoRouter 是否设为默认（维护者决策）
3. **模板系统 + HTML 渲染 + PDF 导出**（PRD P1；UI 模板选择器占位已留）
4. **公式/表格识别质量优化**（P1 承诺）
5. **真实使用反馈驱动**：架构图缺口即由此发现——建议持续以真实手稿压测
6. P2 远期：多页合并、示意图重绘、更多手写编辑语义、风格学习

## 9. 协作模式存档

- 4 worker 并行上限（同时在跑数）、dispatcher 唯一写 main：每 issue 独立分支 → 验收（全量测试+AC 逐条证据+审查+密钥扫描）→ `--no-ff` 合并 → 推送 → BOARD 更新
- 交接全靠 handoff 文档（`handoffs/` 27 份），持续维护删旧；HITL 事项集中汇总（评估集供图、gold 抽检、选型确认均已闭环或临时验收）
- LLM 配额纪律：live 调用均设预算并落盘缓存复用；评估/解析/验证独立 purpose session
