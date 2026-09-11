# Handoff — 修复预处理透视变换产出全黑图（扫描件全部解析为"空白页"）

Branch: `ao/graph2note-15/fix-black-preprocess`（worktree `graph2note-15`，基于 main `19a3c9e`，未 push、未开 PR） · Status → ready-for-review

## 根因（一句话）

`graph2note/preprocess.py::_homography` 把单应矩阵的**非齐次**线性系统 `A h = b`（DLT、固定 H22=1）错当成**齐次**系统 `A h = 0` 来解——对满秩的 8×8 A 取 SVD 的"零空间"（`Vt[-1]`，实际是最小奇异向量，与真实映射无关），得到的垃圾单应把所有输出像素映射到源图之外，`PIL.Image.transform` 默认以黑色填充界外采样 → 透视校正输出纯黑画布，下游裁剪/对比度保持全黑，VLM 收到黑图后回答"本页为空白"。

验证：对恒等 quad（src==dst）旧实现返回 `[[0.016, 0.008, -0.67], …]` 而非单位阵；`np.linalg.lstsq(A, b)` 返回精确单位阵。

## 为什么以前没被发现

旧测试 `test_perspective_corrects_known_quad` 只断言输出 `size` 和 `mode`，从未断言内容存活。bug 自透视校正引入起一直在生产（所有 `perspective_applied=True` 的文档均中招，与是否旋转 90° 无关——旋转只是报告中触发样本的表面特征）。

## 修复内容（`graph2note/preprocess.py`）

1. **`_homography`**：改为 `np.linalg.lstsq(A, b)` 求解真实的 `A h = b`（4 点对时 8×8 精确解，冗余点对时最小二乘）。
2. **`correct_perspective`**：`img.transform(..., fillcolor=白)`——quad 略越界时边缘填充纸白而非黑色（消除黑边/黑图的二因之一）。
3. **`preprocess_image` 退化守卫 `_warp_retains_content`**（纵深防御）：比较 warp 前后降采样灰度的 stddev——有结构的输入（std ≥ 8）若 warp 后塌缩为近似均匀画布（std < max(4, 0.2·std_before)），则弃用该 warp 回退到 deskewed 图，绝不让黑/白空画布进入解析层；空白页（本身无结构）不受影响。反事实验证：把旧 `_homography` monkeypatch 回去后，守卫拦截了垃圾 warp（`perspective_applied=False`），管线输出仍然可读。

## 回归测试（`tests/test_preprocess.py`，+6 个）

- `test_homography_maps_src_points_to_dst` / `test_homography_identity_quad_is_identity`：钉死 DLT 求解的数学正确性。
- `test_perspective_identity_quad_preserves_content`：完美角点 quad warp 后 NCC>0.9、亮度/墨迹存活（旧代码此项全白/全黑，失败）。
- `test_perspective_known_quad_keeps_ink`：已知 quad warp 后墨迹存活（旧断言只查 size/mode 的漏洞由此补齐）。
- `test_preprocess_full_bleed_scan_stays_readable` / `test_preprocess_rotated90_scan_stays_readable`：合成满幅扫描件（含 90° 旋转触发类）端到端跑管线，断言 `perspective_applied=True`（保证 warp 路径被真实执行）且最终输出均值>150、墨迹占比>0.005。
- `test_preprocess_real_scan_fixture_stays_readable`：用仓库内真实扫描件 `eval/fixtures/data/A02.jpg` 端到端驱动。
- `test_warp_guard_rejects_collapsed_canvas`：守卫接受/拒绝语义（黑图拒、白图拒、正常图收、空白页放行）。

**反事实验证**：monkeypatch 回旧 `_homography` 后，7 个新测试全部失败——证明回归网有效。

## 验证记录

- 用户库证据样本 `doc-dd1bb350b9/.../preprocessed_raw.png`（1241×1755，内容旋转 90°）：
  - 修复前逐阶段复现：`_stage_perspective.png` 起全黑（1783×1283，均值 0.0），与用户库中的 `preprocessed.png` 尺寸完全一致；
  - 修复后：final 1656×1235，均值 245.4、墨迹 3.7%、四缘无裁切（edge_touch=0）、逐阶段 NCC 验证几何保留（cropped→final NCC 0.998）。
- `eval/fixtures/data/` A02/A09/A10/A13（修复前 4/4 全黑）：修复后均值 235–239、墨迹 4–6%、文字行方向得分与 raw 一致、无裁切。
- `test-images/` 3 张（修复前因 `perspective_applied=False` 本就正常）：修复后输出与之前一致（无回归）。
- 多模态说明：会话内 look_at / multimodal-looker 均因凭据 401 不可用，视觉复核以上述定量结构指标（亮度、墨迹占比、NCC、行方向得分、边缘接触率）替代完成。
- **`uv run pytest` 全量：399 passed**（含新增 6 个预处理回归测试），51s。

## 受影响数据范围估计（用户库，只读扫描）

扫描 `~/Library/Application Support/Graph2Note/storage/documents/` 43 个文档的最新版本：

- **40/43 的 `preprocessed.png` 为纯黑（均值 0.0），全部需要重新解析**（名单见下；其 `preprocessed_raw.png` 均完好，可直接用修复后的管线重跑，无需重新上传）。
- 3/43 正常（`doc-75d37e7d26`、`doc-db21b82787`、`doc-ef525ae0a8`）——恰为透视未触发的输入。

需重新解析的文档 ID：
`doc-03b20628f7, doc-044a886f5a, doc-0829ccb6a8, doc-0bbc269207, doc-12eacd6e8b, doc-1b7601c71a, doc-283b42fcb2, doc-2e5b047680, doc-48e7551b59, doc-496c777b2b, doc-5c95e3ee69, doc-5e7125ba9e, doc-71b1803c98, doc-803f3425e7, doc-8dc2f6597b, doc-8df2c73b2a, doc-937752071c, doc-968fc5ca10, doc-999989187c, doc-9d836c295b, doc-9ddad73fc1, doc-a334e7eb80, doc-a668bebd84, doc-a8fa623b50, doc-a9483ffb2b, doc-be79971c90, doc-c382813b75, doc-c3de7684d1, doc-c3fed0aa4b, doc-cafa5edddf, doc-d96685d5f7, doc-dd1bb350b9, doc-dec9f12a33, doc-e5a2189657, doc-ea81dae7d5, doc-ed5539f701, doc-f326fd571c, doc-f5352beffe, doc-f70b190916, doc-f9595b92c0`

建议后续动作（不在本任务范围）：提供一个"从 preprocessed_raw 重跑预处理+解析"的修复命令/按钮，或检测 `preprocessed.png` 均值≈0 的文档自动重新入队。

## 已知限制 / follow-ups（非本 bug，未改动）

- 方向判定的投影得分 `rv/cv` 对**极端均匀**的合成栅格会被 `cv→0` 主导而误选 180°（真实手稿未见）；且 90°/270° 在投影指标下天然同分（文字可能上下颠倒），需要翻转语义线索才能区分。
- `_document_quad` 对深色背景上的页面检测是 best-effort；退化 quad（自交/近共线）现在由守卫兜底（弃用 warp 保内容），但未做 quad 凸性校验。
