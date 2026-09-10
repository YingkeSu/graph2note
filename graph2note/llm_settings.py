"""Durable, validated provider/model settings for the local LLM workspace.

The settings file contains only provider ids and model ids.  Credentials stay
in the existing runtime environment/.env lookup and are represented in public
snapshots only as a configured/not-configured boolean.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from eval.gateway import GATEWAYS, _dotenv_get, active_gateway_name


MODEL_PURPOSES = ("parse_visual", "ir_text", "diagram", "classify")
PURPOSE_LABELS = {
    "parse_visual": "解析视觉",
    "ir_text": "IR 文本",
    "diagram": "图形提取",
    "classify": "分类归纳",
}
_ENV_MODEL_KEYS = {
    "parse_visual": "GRAPH2NOTE_MODEL",
    "ir_text": "GRAPH2NOTE_IR_MODEL",
    "diagram": "GRAPH2NOTE_DIAGRAM_MODEL",
    "classify": "GRAPH2NOTE_CLASSIFY_MODEL",
}


class SettingsError(ValueError):
    """Raised when a provider/model settings update is not valid."""


def _default_path() -> Path:
    raw = os.environ.get("GRAPH2NOTE_SETTINGS_FILE", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".graph2note" / "llm-settings.json"


_runtime_path: Path | None = None


def configure_settings_path(path: str | Path | None) -> Path:
    """Set the process-local settings path used by live task resolution."""

    global _runtime_path
    _runtime_path = Path(path).expanduser() if path is not None else None
    return _runtime_path or _default_path()


def runtime_settings_store() -> "LLMSettingsStore":
    return LLMSettingsStore(_runtime_path or _default_path())


def _credential_configured(provider: str) -> bool:
    key_env = GATEWAYS[provider]["key_env"]
    return bool(os.environ.get(key_env, "").strip() or _dotenv_get(key_env))


def _safe_detail(provider: str, detail: Any) -> str | None:
    if detail is None:
        return None
    text = str(detail)
    key_env = GATEWAYS[provider]["key_env"]
    for key in (os.environ.get(key_env, "").strip(), _dotenv_get(key_env)):
        if key:
            text = text.replace(key, "[redacted]")
    return text[:240]


def _provider_models(provider: str, purpose: str) -> list[str]:
    return list(GATEWAYS[provider].get("models", {}).get(purpose, []))


def _default_channels(provider: str) -> dict[str, dict[str, str]]:
    channels: dict[str, dict[str, str]] = {}
    for purpose in MODEL_PURPOSES:
        configured = os.environ.get(_ENV_MODEL_KEYS[purpose], "").strip()
        supported = _provider_models(provider, purpose)
        default = GATEWAYS[provider].get("defaults", {}).get(purpose)
        model = configured if configured in supported else default
        if not model and supported:
            model = supported[0]
        channels[purpose] = {"provider": provider, "model": model or ""}
    return channels


class LLMSettingsStore:
    """Read-through JSON settings store; every resolve reads the latest file."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else (_runtime_path or _default_path())

    def _read_channels(self) -> dict[str, dict[str, str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
            raw = {}
        provider = _safe_active_provider()
        channels = _default_channels(provider)
        stored = raw.get("channels") if isinstance(raw, dict) else None
        if not isinstance(stored, dict):
            return channels
        for purpose in MODEL_PURPOSES:
            item = stored.get(purpose)
            if not isinstance(item, dict):
                continue
            candidate = {"provider": item.get("provider"), "model": item.get("model")}
            if _valid_channel(purpose, candidate):
                channels[purpose] = {
                    "provider": str(candidate["provider"]),
                    "model": str(candidate["model"]),
                }
        return channels

    def resolve(self, purpose: str) -> dict[str, str]:
        if purpose not in MODEL_PURPOSES:
            raise SettingsError(f"未知用途：{purpose}")
        return dict(self._read_channels()[purpose])

    def snapshot(self) -> dict[str, Any]:
        channels = self._read_channels()
        providers = []
        for provider, config in GATEWAYS.items():
            providers.append({
                "id": provider,
                "name": config.get("label", provider),
                "credential_configured": _credential_configured(provider),
                "capabilities": {
                    purpose: {"models": _provider_models(provider, purpose)}
                    for purpose in MODEL_PURPOSES
                },
            })
        return {
            "purposes": list(MODEL_PURPOSES),
            "purpose_labels": dict(PURPOSE_LABELS),
            "providers": providers,
            "channels": {
                purpose: {
                    **channels[purpose],
                    "purpose": purpose,
                    "label": PURPOSE_LABELS[purpose],
                }
                for purpose in MODEL_PURPOSES
            },
        }

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        candidate = self._read_channels()
        patches = updates.get("channels") if isinstance(updates, dict) else None
        if patches is None:
            patches = updates
        if not isinstance(patches, dict) or not patches:
            raise SettingsError("channels 必须是非空对象")
        unknown = set(patches) - set(MODEL_PURPOSES)
        if unknown:
            raise SettingsError(f"未知用途：{', '.join(sorted(unknown))}")
        for purpose, patch in patches.items():
            if not isinstance(patch, dict):
                raise SettingsError(f"用途 {purpose} 的配置必须是对象")
            next_channel = dict(candidate[purpose])
            for key in ("provider", "model"):
                if key in patch:
                    value = patch[key]
                    if not isinstance(value, str) or not value.strip():
                        raise SettingsError(f"用途 {purpose} 的 {key} 不能为空")
                    next_channel[key] = value.strip()
            if not _valid_channel(purpose, next_channel):
                provider = next_channel.get("provider")
                model = next_channel.get("model")
                raise SettingsError(
                    f"用途 {purpose} 不支持 provider/model：{provider!r}/{model!r}"
                )
            candidate[purpose] = next_channel
        self._write_channels(candidate)
        return self.snapshot()

    def _write_channels(self, channels: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "channels": channels}, fh,
                          ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise


def _safe_active_provider() -> str:
    try:
        return active_gateway_name()
    except Exception:
        return "opencode"


def _valid_channel(purpose: str, channel: dict[str, Any]) -> bool:
    provider = channel.get("provider")
    model = channel.get("model")
    return (
        purpose in MODEL_PURPOSES
        and isinstance(provider, str)
        and provider in GATEWAYS
        and isinstance(model, str)
        and model in _provider_models(provider, purpose)
    )


def resolve_channel(purpose: str) -> dict[str, str]:
    """Resolve the latest effective channel for a task without caching it."""

    return runtime_settings_store().resolve(purpose)


def probe_channel(
    provider: str,
    purpose: str,
    model: str,
    *,
    probe: Callable[[str, str, str], Any] | None = None,
) -> dict[str, Any]:
    """Probe one configured channel and normalize safe, UI-facing status."""

    if provider not in GATEWAYS or not _valid_channel(purpose, {"provider": provider, "model": model}):
        return {"provider": provider, "purpose": purpose, "model": model,
                "status": "request_failed", "detail": "配置无效"}
    if probe is None and not _credential_configured(provider):
        return {"provider": provider, "purpose": purpose, "model": model,
                "status": "missing_credentials", "detail": f"未配置 {GATEWAYS[provider]['key_env']}"}
    try:
        result = probe(provider, purpose, model) if probe is not None else _default_probe(provider, purpose, model)
        if isinstance(result, dict):
            status = str(result.get("status", "available"))
            detail = _safe_detail(provider, result.get("detail"))
        else:
            status, detail = ("available" if result is not False else "request_failed"), None
        if status not in {"available", "missing_credentials", "auth_failed", "request_failed"}:
            status = "request_failed"
        return {"provider": provider, "purpose": purpose, "model": model,
                "status": status, "detail": detail}
    except Exception as exc:
        code = getattr(exc, "code", None)
        status = "auth_failed" if code in (401, 403) or "401" in str(exc) or "403" in str(exc) else "request_failed"
        return {"provider": provider, "purpose": purpose, "model": model,
                "status": status, "detail": _safe_detail(provider, exc)}


def _default_probe(provider: str, purpose: str, model: str) -> dict[str, str]:
    from eval.gateway import GatewayError, post_gateway, resolve_session_for

    session_purpose = "diagram" if purpose == "diagram" else "parse" if purpose == "parse_visual" else "routeb"
    try:
        post_gateway(
            {"model": model, "max_tokens": 1,
             "messages": [{"role": "user", "content": "ping"}]},
            provider=provider,
            session=resolve_session_for(session_purpose, model),
            timeout=15,
            user_agent="graph2note-settings-probe/0.1",
        )
    except GatewayError:
        raise
    return {"status": "available"}


__all__ = [
    "LLMSettingsStore",
    "MODEL_PURPOSES",
    "PURPOSE_LABELS",
    "SettingsError",
    "configure_settings_path",
    "probe_channel",
    "resolve_channel",
    "runtime_settings_store",
]
