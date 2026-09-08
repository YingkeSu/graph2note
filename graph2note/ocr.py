"""本地 OCR 引擎封装（issue 08 / Route B）。

选型结论：**tesseract 5.x**（本机已装，含 chi_sim/chi_tra/eng，163 语言，开源本地优先）。
paddleocr/rapidocr/easyocr 未在本机安装，故不引入额外依赖——直接 subprocess 调 tesseract 二进制。
网络隔离：OCR 纯本地，不触网。调用失败/无引擎时**降级**（返回空文本 + 明确警告），不崩溃。

依赖检测：``tesseract_available()`` 探测二进制与简体中文语言包；测试用 ``pytest.importorskip``
守护（无引擎则跳过在线校验路径相关测试）。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import time

# 可经 GRAPH2NOTE_OCR_ENGINE 覆盖（默认 tesseract）。
ENGINE = "tesseract"
DEFAULT_LANG = "chi_sim+eng"
CALL_TIMEOUT_SECONDS = 120.0


class OCRError(RuntimeError):
    """OCR 引擎调用失败（不可用、超时、非零退出）。"""


def tesseract_binary() -> str | None:
    return shutil.which("tesseract")


def tesseract_available(lang: str = DEFAULT_LANG) -> bool:
    """探测 tesseract 二进制 + 简体中文语言包是否可用（不触网）。"""
    exe = tesseract_binary()
    if not exe:
        return False
    if platform.system() == "Windows":
        return True  # Windows 端语言包探测从简；POSIX 下用 --list-langs
    try:
        proc = subprocess.run(
            [exe, "--list-langs"], capture_output=True, text=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return False
    langs = (proc.stdout or "") + (proc.stderr or "")
    for need in lang.split("+"):
        if need and need not in langs:
            return False
    return True


def ocr_available(lang: str = DEFAULT_LANG) -> bool:
    """当前配置的 OCR 引擎是否可用（tesseract + 目标语言）。"""
    if ENGINE != "tesseract":
        return False
    return tesseract_available(lang)


def ocr_image(image_path: str, *, lang: str = DEFAULT_LANG) -> tuple[str, dict]:
    """对图片做 OCR，返回 (text, meta)。失败/空引擎：返回 ("", meta) 并写明原因，不抛异常。

    meta 含：engine、lang、可用的版本、chars、latency_seconds、error（无则 None）。
    """
    exe = tesseract_binary()
    meta: dict = {
        "engine": ENGINE,
        "lang": lang,
        "version": None,
        "chars": 0,
        "latency_seconds": None,
        "error": None,
    }
    if not exe:
        meta["error"] = f"{ENGINE} binary not found on PATH"
        return "", meta
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=20
        )
        meta["version"] = (proc.stdout or proc.stderr or "").strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        meta["version"] = "<unknown>"

    if not tesseract_available(lang):
        meta["error"] = f"tesseract missing language pack for {lang!r}"
        return "", meta

    start = time.monotonic()
    try:
        proc = subprocess.run(
            [exe, image_path, "stdout", "-l", lang],
            capture_output=True, text=True, timeout=CALL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        meta["latency_seconds"] = round(CALL_TIMEOUT_SECONDS, 2)
        meta["error"] = "tesseract timed out"
        return "", meta
    except (OSError, subprocess.SubprocessError) as exc:
        meta["error"] = f"tesseract failed: {exc}"
        return "", meta
    meta["latency_seconds"] = round(time.monotonic() - start, 2)
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        meta["error"] = f"tesseract exited {proc.returncode}: {stderr[:200]}"
        return "", meta
    text = (proc.stdout or "").strip()
    meta["chars"] = len(text.replace("\n", ""))
    return text, meta


def ocr_mean_confidence(image_path: str, *, lang: str = DEFAULT_LANG) -> dict:
    """用 tesseract TSV 输出求字符/词平均置信度（特征分类信号，Route B 路由决策）。

    返回 {mean_conf, count, error|None}。无引擎/失败时 mean_conf=None。纯本地，不触网。
    """
    exe = tesseract_binary()
    out = {"mean_conf": None, "count": 0, "error": None}
    if not exe:
        out["error"] = "tesseract not found"
        return out
    try:
        proc = subprocess.run(
            [exe, image_path, "stdout", "-l", lang, "tsv"],
            capture_output=True, text=True, timeout=CALL_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        out["error"] = f"tsv failed: {exc}"
        return out
    if proc.returncode != 0:
        out["error"] = f"tsv exited {proc.returncode}"
        return out
    header = None
    confs: list[float] = []
    for line in (proc.stdout or "").splitlines():
        if header is None:
            header = line.split("\t")
            continue
        row = line.split("\t")
        if len(row) < len(header):
            continue
        try:
            conf = float(row[header.index("conf")])
        except (ValueError, IndexError):
            continue
        if conf >= 0:
            confs.append(conf)
    if not confs:
        out["error"] = "no confident words in TSV"
        return out
    out["mean_conf"] = round(sum(confs) / len(confs), 2)
    out["count"] = len(confs)
    return out