# 实际应用诊断与已有方案调研

日期：2026-09-15。范围：只诊断、调研、发布 issues；没有实现修复，也没有重新导入、重解析或调用付费模型。

## 实测环境与边界

- 运行中桌面应用 Graph2Note，PID 28193，HTTP `http://127.0.0.1:57819`；端口为本次会话值，后续用 `lsof -nP -iTCP -sTCP:LISTEN` 重新确认。
- GET `/api/config` 确认真实库为 `/Users/suyingke/Library/Application Support/Graph2Note/storage`，不是仓库 `.g2n-storage`。
- 本地源码 HEAD：`b56e3c4fbf20b32d1e42fb8365e102276c803ced`。没有验证打包二进制与 HEAD 逐文件一致；以下根因由源码与实际 API/页面结果互相印证。
- Playwright 打开真实服务的 `#library`、`#doc/pdf-c33a66dadca2388d-paper`，读取 DOM 与 console；未操作原生窗口，macOS WebView 特有兼容性仍需实现时验收。
- 17 篇论文全部为 `done` / `text-layer`，17/17 `view.meta.title` 为空。这里只确认标题字段总体计数，没有宣称逐字段人工评审全部完成。

## 已确认的问题

### D1：原件存在，预览连接缺失

库页面 17 条 `/api/documents/<id>/thumbnail` 请求均 404；favicon 404 是无关噪声。

GPT-4 样本 `pdf-c33a66dadca2388d`：

| 请求 | 实测 |
|---|---|
| `/api/papers/pdf-c33a66dadca2388d/original` | 200，application/pdf，5,245,564 bytes |
| `/api/papers/pdf-c33a66dadca2388d/page/0` | 200，image/png，318,177 bytes |
| `/api/documents/pdf-c33a66dadca2388d-paper/thumbnail` | 404 |
| 阅读页 `.paper-section` | 510 个 |

源码定位：`graph2note/webapp.py:1635` 缩略图只读取 latest.preprocessed_path；`graph2note/papers/pipeline.py` 的 `_commit_text_layer` 则明确保存 `preprocessed_path=None`。专用 `webstatic/js/views/paper.js` 只渲染元数据、章节、参考文献，没有调用原 PDF 或逐页预览。`/view` 返回字段也没有 original_url/pdf_id。因而不能把问题归因于 PDF 文件损坏或浏览器不支持 PDF。

### D2：章节规则把印记、编号、图表内容提升为标题

| 样本 | 页数 | sections |
|---|---:|---:|
| GPT-4 | 100 | 510 |
| GPT-3 | 75 | 437 |
| Toy Models of Superposition | 62 | 387 |
| MoBA | 15 | 92 |

章节数量不是正确性判据；确定错误是 GPT-4 的 `arXiv:2303.08774v6 [cs.CL] 4 Mar 2024` 被列为一级标题，独立 `1` 与 `Introduction` 分成两个章节。

直接对原 PDF 调用 `read_text_layer` / `detect_headings`：body_size=10.0，510 headings，其中 size=309、number=191、name=10；arXiv 印记为 20pt，reason=size。`structure.py:190` 仅凭字号高于正文 1pt 且文本不像句子即可提升标题。`textlayer.py` 默认 `get_text('text')` / `get_text('dict')`，TextLine 未保存 bbox/方向，后续难以识别侧边印记及栏结构。官方说明默认 PDF 文本顺序不保证自然阅读顺序；但本次没有逐段标注双栏全文，不能把所有错序都宣称已定量复现。

同一印记在 heading 原始证据 page_index=0，而 `/view` 的该 section 为 p.2，说明标题及后续正文跨页定位也需要专项验收，不应只调整目录数量。

### D3：导入没有调用已有元数据能力

`pipeline.py` 的 `_commit_text_layer` 写 `meta=model.PaperMeta()`、`references=[]`；文件名 stem 用作文档标题。P2 的 `POST /api/papers/parse-metadata` 是独立无状态接口。运行中的 17 篇标题均为空，与该未接线状态一致。`paper.json` 与 `record.json.paper` 是既有双存储议题；不能仅凭双存储就断言它是此次空元数据的主因。

### D4：论文问答接线与证据粒度风险

已有 `pdfqa.py`、`pdfqa_sessions.py`、`pdfsearch.py` 和 `/api/pdf/ask`，包含多轮持久化、引用校验与调用限制。专用 paper 阅读页未接入这些功能。论文聚合记录写 page_index=0，而 pdfsearch 以记录级 page_index 为检索来源：若直接接通，可能把后页全文命中归到第一页。这是源码证据支持的集成风险，未进行模型回答实测，故 issue 06 要先建立检索定位验收。

## 可重复的只读失败检查

在仓库使用 `.venv/bin/python` 执行以下脚本；更换为当前服务端口即可。该命令已运行，三个断言均 FAIL，退出码 1；读取真实用户症状，不修改文档。

```python
import json, urllib.request, urllib.error
base = 'http://127.0.0.1:57819'
id = 'pdf-c33a66dadca2388d-paper'
x = json.load(urllib.request.urlopen(base + '/api/papers/' + id + '/view'))
checks = {
    'no arxiv stamp heading': not any(s['title'].startswith('arXiv:') for s in x['sections']),
    'metadata title present': bool(x['meta']['title']),
}
try:
    response = urllib.request.urlopen(base + '/api/documents/' + id + '/thumbnail')
    checks['thumbnail available'] = response.status == 200
except urllib.error.HTTPError:
    checks['thumbnail available'] = False
for name, passed in checks.items():
    print('PASS' if passed else 'FAIL', name)
assert all(checks.values()), 'real paper recognition/preview regressions reproduced'
```

实际输出：

```text
FAIL no arxiv stamp heading
FAIL metadata title present
FAIL thumbnail available
AssertionError: real paper recognition/preview regressions reproduced
```

## 联网调研与选型建议

下面均为 2026-09-15 查阅的官方项目/文档。未安装候选解析器，也未做同样本性能对比；建议不是已验证的本项目性能结论。

| 候选 | 已有能力与可借鉴部分 | 本项目取舍 |
|---|---|---|
| [PDF.js](https://mozilla.github.io/pdf.js/) | 基于 Web 标准解析和渲染 PDF | 原文阅读首选候选；本地打包并验证 WebView，已有页图接口作为回退。解析质量不应阻塞原文阅读。 |
| [GROBID](https://grobid.readthedocs.io/en/latest/Introduction/) | 学术文献结构、书目信息与引用提取 | 元数据/参考文献专门候选；部署服务和资源成本需测量，先接好已有 P2。 |
| [Docling](https://github.com/docling-project/docling) | 布局、阅读顺序、表格、OCR 与结构化文档表示 | 与现有规则在真实论文上对比。其 README 仍把 metadata extraction 列在 coming soon，不能以它替代已验证的专业元数据解析。 |
| [PyMuPDF 文本提取](https://pymupdf.readthedocs.io/en/latest/recipes-text.html) | 文本坐标、排序等提取接口 | 轻量路径可保留，但必须保留坐标并处理栏结构；sort=True 不足以保证复杂论文阅读顺序。 |
| [Docling 格式表](https://docling-project.github.io/docling/usage/supported_formats/) | 多格式转统一表示 | 是提取能力清单，不是本应用预览支持承诺，也不意味着转换版与原版视觉一致。 |
| [LibreOffice 转换过滤器](https://help.libreoffice.org/latest/en-US/text/shared/guide/convertfilters.html) | Office 文件转换 | DOCX/PPTX 派生 PDF 的候选；依赖、字体和保真度要在 macOS 打包环境验收。 |
| [epub.js](https://github.com/futurepress/epub.js) | 浏览器电子书阅读 | EPUB 专用阅读候选；脚本与远程资源默认禁用。 |
| [Zotero 阅读器交互](https://www.zotero.org/support/kb/keyboard_shortcuts) | PDF/EPUB/快照阅读的统一操作 | 借鉴原件阅读、导航、定位的一致性，不照搬整套文献管理。 |
| [pi agent core](https://raw.githubusercontent.com/badlogic/pi-mono/main/packages/agent/README.md) | 模型与应用消息转换、工具执行事件、取消、轮次结束停止钩子 | 借鉴 loop 与界面事件边界；保持现有 Python 技术栈。 |
| [pi compaction](https://raw.githubusercontent.com/badlogic/pi-mono/main/packages/coding-agent/docs/compaction.md) | 长会话压缩机制 | 借鉴上下文管理，论文证据 ID/解析版本必须保留；压缩摘要不能成为无原文支持的证据。 |

### Loop 与 harness 的职责

以下是针对本项目的设计建议，不是声称 pi 已替本项目实现：

- Loop 负责当前轮模型决策和检索/读页工具交互；固定总结优先采用分块提取与合成流程。
- Harness 负责输入边界、论文范围、预算、会话落盘、取消、恢复、trace 与评测。工具集合不暴露 shell、写文件或任意网络。
- 流式事件面向界面展示可理解的进度和来源，不展示或持久化模型内部思维链。
- 终止条件必须可满足：正常回答、证据不足、取消、预算到达、重复空结果都进入终态。pi 的轮后停止钩子不会替代在途调用取消，需要显式中断。

## 与既有 issue 的关系

本次不关闭、不改写旧票：[Y4 真实论文样本](../structure-paper-weekly/issues/Y4-real-paper-fixtures.md)；旧目录还已有 Y1 PATCH 清字段、Y2 双存储、Y5 元数据启发式问题。新 02 承接导入接线与历史回填，新 03 承接已复现结构错误；新 09 复用旧 Y4 样本工作，避免重复建设。

交付索引：[BOARD.md](BOARD.md)。9 个 issues 均有依赖和验收条件；尚未执行任何功能验收，也未声称修复通过。
