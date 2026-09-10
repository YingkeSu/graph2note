"""Route B（issue 08）：图片 → 传统 OCR → 文本 LLM 结构化 → Document IR。

复用 issue 12 的「两阶段」经验：stage-1 先把（OCR 噪声）文本整理成 Markdown 中间表示，
stage-2 用确定性 markdown-parser 转 Document IR（schema 校验）。文本 LLM 走网关
非视觉能力（``eval.gateway.transcribe_text``，routeb 用途独立直出 session），OCR 本地
tesseract（``graph2note.ocr``，不触网）。

Router 缝：本模块提供 :class:`RouteBRouter`（实现 ``RecognitionRouter.recognize``）与
:class:`AutoRouter`（特征路由：默认 Route A、高印刷置信度时才切 Route B）。上游
``parse_document`` 只依赖 ``RecognitionRouter.recognize``，因此接入第二种策略对上层**零改动**
（AC 验证，见 test_route_b 与 test_router_route_b_upstream_zero_change）。

失败路径：OCR 空 → 空 IR（降级，不崩溃）；文本 LLM 空/异常 → 回退用原始 OCR 文本当
Markdown（永不空）；IR schema 校验失败 → 空 IR + 明确警告。绝不让一次失败使整链崩溃。
"""

from __future__ import annotations

import os

from .ir import DocumentIR, IRValidationError, load_dict_as_ir
from .llm_settings import resolve_channel
from .ocr import ocr_available, ocr_image, ocr_mean_confidence
from .router import RecognitionRouter, RouteResult, _inject_degrade_source
from .vlm import _markdown_to_ir

DEFAULT_ROUTE_B_MODEL = "glm-5.3-flash"  # 稳定直出文本模型；与 eval.gateway.ROUTE_B_TEXT_MODEL 一致
PRINT_CONFIDENCE_THRESHOLD = 55.0  # tesseract 平均置信度 >= 阈值 → 判「印刷类」倾向 Route B


def _empty_ir() -> DocumentIR:
    return DocumentIR(document_type="note", blocks=[])


def route_b_chain(
    image_path: str,
    model: str | None = None,
    *,
    provider: str | None = None,
    ocr_caller=None,
    text_caller=None,
    ocr_text: str | None = None,
    max_retries: int = 2,
    diagram_source: str | None = None,
) -> RouteResult:
    """Route B 全链：OCR -> 文本 LLM 结构化 Markdown -> Document IR（schema 校验）。

    可注入 ``ocr_caller(image_path)->(text,meta)`` 与 ``text_caller(ocr_text, model, recover)->(content,meta)``
    以便离线测试；未注入时用真实 tesseract + eval.gateway.transcribe_text。
    """
    if model is None:
        channel = resolve_channel("ir_text")
        model = channel["model"]
        provider = provider or channel["provider"]

    ocr_meta: dict = {}
    if ocr_caller is not None:
        ocr_text, ocr_meta = ocr_caller(image_path)
    elif ocr_text is None:
        ocr_text, ocr_meta = ocr_image(image_path)

    if not (ocr_text or "").strip():
        return RouteResult(
            document=_empty_ir(),
            degraded_block_indices=[],
            retries=0,
            strategy="route_b",
            raw_content="",
            attempts=[{"stage": "ocr", "chars": (ocr_meta or {}).get("chars", 0)}],
            warnings=[f"OCR returned empty text; produced empty IR ({ocr_meta.get('error') or 'no text'})"],
        )

    raw = ocr_text.strip()
    warnings: list[str] = []
    attempts: list[dict] = [{"stage": "ocr", "chars": (ocr_meta or {}).get("chars", len(raw))}]
    markdown = ""
    retries = 0

    # stage-1：文本 LLM 把 OCR 文本整理成 Markdown 中间表示
    for attempt in range(max_retries + 1):
        recover = attempt > 0
        if text_caller is not None:
            content, tmeta = text_caller(raw, model, recover=recover)
        else:
            from eval.gateway import transcribe_text
            content, tmeta = transcribe_text(raw, model, provider=provider)
        tmeta = dict(tmeta or {})
        tmeta.setdefault("model", model)
        if provider is not None:
            tmeta.setdefault("provider", provider)
        attempts.append({"attempt": attempt, "stage": "text_llm", "meta": tmeta})
        if (content or "").strip() and not _looks_like_refusal(content):
            markdown = content.strip()
            break
        retries += 1
        warnings.append(
            f"text LLM returned empty/refusal on attempt {attempt} "
            f"(raw_len={len(content or '')})"
        )

    if not markdown:
        # 降级：回退用原始 OCR 文本当 Markdown，保证非空输入 → 非空 IR
        markdown = raw
        warnings.append("fell back to raw OCR text as markdown (text LLM empty/error)")

    # stage-2：确定性 markdown -> Document IR（保序、非空），schema 校验
    ir = _markdown_to_ir(markdown)
    try:
        doc = load_dict_as_ir(ir)
    except IRValidationError as exc:
        doc = _empty_ir()
        warnings.append(f"IR validation failed; degraded to empty IR: {exc}")

    degraded: list[int] = []
    if document_nonempty(doc) and diagram_source:
        degraded = _inject_degrade_source(doc, diagram_source)

    return RouteResult(
        document=doc,
        degraded_block_indices=degraded,
        retries=retries,
        strategy="route_b",
        raw_content=markdown,
        attempts=attempts,
        warnings=warnings,
    )


def document_nonempty(doc: DocumentIR) -> bool:
    return bool(getattr(doc, "blocks", None))


_REFUSAL_MARKERS = (
    "无法识别", "无法整理", "无可整理", "噪声过大", "无法辨认", "无法恢复",
    "不便整理", "拒绝", "cannot", "unable", "noise", "no content",
    "无可输出", "没有可识别", "无可识别",
)


def _looks_like_refusal(content: str) -> bool:
    """探测模型把 OCR 判为噪声而拒绝/只回占位句的情况（视为空，走回退到原始 OCR）。"""
    c = (content or "").strip()
    if not c or len(c) < 25:
        return True
    low = c.lower()
    return any(m in low for m in _REFUSAL_MARKERS)


class RouteBRouter(RecognitionRouter):
    """Route B 路由：完整 OCR -> 文本 LLM 结构化 -> IR。实现同一 ``recognize`` 缝。"""

    def __init__(
        self,
        model: str | None = None,
        *,
        provider: str | None = None,
        ocr_caller=None,
        text_caller=None,
        max_retries: int = 2,
        session: str | None = None,
    ) -> None:
        super().__init__(model or DEFAULT_ROUTE_B_MODEL)
        self._configured_model = model
        self.provider = provider
        self._ocr_caller = ocr_caller
        self._text_caller = text_caller
        self.max_retries = max_retries
        self.session = session
        self._image_path: str | None = None

    def recognize(
        self,
        image_path: str,
        *,
        diagram_source: str | None = None,
    ) -> RouteResult:
        self._image_path = image_path
        model = self._configured_model
        provider = self.provider
        if model is None:
            channel = resolve_channel("ir_text")
            model = channel["model"]
            provider = provider or channel["provider"]
        self.model = model
        self.provider = provider
        return route_b_chain(
            image_path,
            model,
            provider=provider,
            ocr_caller=self._ocr_caller,
            text_caller=self._text_caller,
            max_retries=self.max_retries,
            diagram_source=diagram_source,
        )


def classify_route_features(
    image_path: str,
    *,
    ocr_caller=None,
    ocr_text: str | None = None,
    confidence: dict | None = None,
) -> dict:
    """输入特征分类：返回印刷/手写倾向信号，供 AutoRouter 路由决策。

    - ``mean_conf``：tesseract 平均置信度（OCR 读得越自信 → 越像清印刷）。
    - ``chars``：OCR 识别出的总字符量（富文本页应有明显非零量）。
    - ``print_likelihood``：0~1；conf>=阈值且字符量够 → 高，判倾向 Route B（印刷友好）；
      手写/图示页 tesseract 置信度低 → 致 Route A。
    """
    if confidence is None:
        if ocr_caller is not None or ocr_text is None:
            confidence = ocr_mean_confidence(image_path)
        else:
            confidence = {"mean_conf": None, "count": 0, "error": None}
    mean_conf = confidence.get("mean_conf")
    chars = confidence.get("count", 0)
    if mean_conf is None:
        # 无置信度信号：无法判定 → 保守按非印刷（Route A）处理
        return {"mean_conf": None, "chars": chars, "print_likelihood": 0.0,
                "basis": "no-confidence"}
    print_likelihood = 1.0 if mean_conf >= PRINT_CONFIDENCE_THRESHOLD and chars > 0 else 0.0
    return {"mean_conf": mean_conf, "chars": chars, "print_likelihood": print_likelihood,
            "basis": "tesseract-tsv-confidence"}


class AutoRouter(RecognitionRouter):
    """特征路由：按输入特征在 Route A / Route B 之间选择。env ``GRAPH2NOTE_ROUTE``
    强制覆盖（auto|a|b，默认 auto）。结论（issue 08）：Route A 在评估集（手写/图示）全面占优，
    因此 auto 默认走 Route A；仅当 OCR 平均置信度高分（清印刷特征）才切 Route B（印刷友好）。
    """

    def __init__(
        self,
        model: str = DEFAULT_ROUTE_B_MODEL,
        *,
        route_a: RecognitionRouter | None = None,
        route_b_router: RecognitionRouter | None = None,
        feature_fn=None,
    ) -> None:
        super().__init__(model)
        from .router import RouteARouter
        self._route_a = route_a or RouteARouter(model)
        self._route_b = route_b_router or RouteBRouter(model)
        self._feature_fn = feature_fn  # image_path->dict（可注入离线测试）

    def _choose_route(self, image_path: str) -> RecognitionRouter:
        mode = os.environ.get("GRAPH2NOTE_ROUTE", "auto").lower()
        if mode == "a":
            return self._route_a
        if mode == "b":
            return self._route_b
        feat = self._feature_fn(image_path) if self._feature_fn else classify_route_features(image_path)
        # 特征=OCR 置信度机制；print_likelihood>=0.5 → Route B（印刷），否则 Route A（默认，手写/图示优）
        if (feat or {}).get("print_likelihood", 0) >= 0.5:
            return self._route_b
        return self._route_a

    def recognize(self, image_path: str, *, diagram_source: str | None = None) -> RouteResult:
        delegate = self._choose_route(image_path)
        return delegate.recognize(image_path, diagram_source=diagram_source)


__all__ = [
    "route_b_chain",
    "RouteBRouter",
    "AutoRouter",
    "classify_route_features",
    "PRINT_CONFIDENCE_THRESHOLD",
]
