# 质量评估 harness（Spike 1）

对候选视觉模型在评估集上做「图片 → VLM → Markdown」直转质量对比，计算 EditRate 并输出报告。

## 用法

```bash
# 列出评估集样本
python -m eval.cli list

# 对指定模型跑全量评估集（同图同模型结果缓存于 eval/cache/，不重复调用）
python -m eval.cli run --model glm-5.3-flash
python -m eval.cli run --model deepseek-v4-flash-vision-exp

# 强制重新调用（忽略缓存）
python -m eval.cli run --model glm-5.3-flash --nocache

# 跑指定样本子集（冒烟）
python -m eval.cli run --model glm-5.3-flash --only 01-requirements-arch
```

密钥：运行时从环境变量 `OPENCODE_API_KEY` 读取（缺省回退到仓库根 `.env`，已 gitignore）。
调用参数见 `docs/llm/opencode-go.md`：`x-opencode-session` 头、`max_tokens=10000`、
`chat/completions` 端点、图片以 base64 data URL 传入。

## 输出

- `eval/reports/report-<model>.md`：Markdown 报告（总体 EditRate、分类目指标、样本明细、涂改专项）
- `eval/reports/detail-<model>.json`：每样本 gold/pred 全文 + 指标 + 调用 meta（成本/耗时/token）
- `eval/cache/*.json`：逐样本缓存（gitignore）

## EditRate 定义

`EditRate = 编辑字符数 / max(len(gold), 1)`。
编辑字符数 = 把 pred 变换为 gold 的最小字符级编辑操作数（插入/删除/替换各计 1）。
实现与单元测试见 `eval/editerate.py` 与 `tests/test_editerate.py`（不触网）。

## 模块

- `eval/gateway.py` —— opencode go 网关调用；含针对「思考过长被截断、正文为空」的递减 max_tokens 回退。
- `eval/dataset.py` —— 评估集加载（fixtures 约定）。
- `eval/harness.py` —— 跑分 + 汇总 + 报告渲染。
- `eval/cli.py` —— 命令行入口。
- `eval/fixtures/` —— 评估集（metadata.json、gold/、CATEGORIES.md 类目与扩充约定）。
- `tests/test_editerate.py`、`tests/test_dataset.py` —— 离线单测。

## 注意

- gold 目前为 AI 草拟、**未经人工校对**（HITL 待维护者），EditRate 数值因此偏高，不具选型结论意义；
  仅用于验证 harness 可用。《评估集扩充与 gold 校对》见 `../.scratch/manuscript-compiler-mvp/handoffs/01-spike1-vision-quality-eval.md`。