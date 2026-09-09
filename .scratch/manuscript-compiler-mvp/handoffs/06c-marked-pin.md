# Handoff — Issue 06c：marked 版本锁定 + renderer 双签名兼容（预览修复运行时生效）

**Status: in-review** · Worker：AO fix worker · Branch：`dev/06c-marked-pin`（自 origin/main，含 06b 合并）
**Verified:** node 单测 + 真机 CDN marked 双版本 runtime 验证 + pytest（`295 passed, 2 skipped`）

---

## 1. 根因（一句话）

06b 的重写代码正确但 **index.html 的 marked CDN 标签没锁版本**——
`npm/marked/marked.min.js` 拉到最新 v12+，其 `renderer.image` 入参从
`(href, title, text)` 字符串变成了单个 token 对象 `{href,title,text,…}`，
旧 renderer 里 `isAssetRef(href)` 对对象恒 false → 重写静默失效 →
图片仍按页面原点 404（单测按旧签名构造所以绿但浏览器不生效）。

**回归复现**（node + CDN marked v12 真机验证）：旧 renderer 输出
`<img src="[object Object]">` → 图片损坏。

## 2. 修复（双保险）

1. **锁版本**：`index.html` 改为 `marked@4.3.0/marked.min.js`（注释注明原因）。
   4.3.0 与 renderer 的字符串签名一致；KaTeX 保持 0.16.9 锁定不动。
2. **双签名兼容**：`assets.js` 新增纯函数 `normalizeImageArgs(hrefOrToken, title, text)`
   —— v4 字符串形态与 v12+ token 对象形态统一归一为 `{href,title,text}`
   （非字符串安全降级为 `""`/`null`）；`app.js` 的 `renderer.image` 改走该归一
   再重写。今后 CDN 再变签名也不崩。

## 3. 验证

```bash
node tests/assets_rewrite.cjs        # 06b 五例 + 06c 新增：v4 字符串形态、
                                     # v12+ token 对象形态、token href 端到端重写、
                                     # token 外链不动、畸形参数安全
python3 -m pytest -p no:warnings     # 295 passed, 2 skipped（不回退）
```

**真机 runtime 验证**（临时脚本 /tmp，不入库）：vm 沙箱加载 CDN 真实 marked
（`marked@4.3.0` 与 `marked@latest` v12+）+ 仓库 assets.js + app.js 同款
renderer，渲染 `![架构图](assets/arch.png)`：
- 两个版本均输出 `src="/api/documents/doc-42/assets/arch.png"` ✓，外链不动 ✓；
- 旧（06b）renderer + v12 复现 `src="[object Object]"` 失败，证实根因。

**手测路径**：上传 `test-images/01-requirements-arch.jpg` → 三栏预览栏应显示
重建图（预览图 src 为 `/api/documents/<id>/assets/<name>`）。

## 4. 风险 / 备注

- marked 锁 4.3.0 + 兼容层：即使有人日后把 pin 升到 v12+，行为仍正确（已验证）。
- 若 CDN 不可达，`window.marked` 缺失 → 预览降级占位（既有行为，编辑不受影响）。
- 无密钥、无新依赖、零构建不变。