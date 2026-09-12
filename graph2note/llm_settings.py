"""Durable, validated provider/model settings for the local LLM workspace.

The settings file holds two things:

- ``channels``: which provider/model each purpose (parse/IR/diagram/classify) uses.
- ``custom_providers``: user-defined OpenAI-compatible vendor entries (issue A3),
  including their API key.

Built-in provider credentials stay in the existing runtime environment/.env lookup
and are represented in public snapshots only as a configured/not-configured boolean.
Custom provider keys live in this file (inside the gitignored storage dir) and are
**write-only** over the API: GET/UI always returns only a "已设置/未设置" boolean, never
the plaintext.  A custom vendor is a plain OpenAI Chat Completions endpoint
(``{base_url}/chat/completions`` + ``Bearer`` key) with the model name passed through
verbatim (never ``map_model``-rewritten).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from eval.gateway import (
    GATEWAYS,
    _dotenv_get,
    active_gateway_name,
    configure_custom_providers,
    fetch_provider_models as _gateway_fetch_models,
    gateway_config,
)


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

# 自定义供应商（issue A3）
CUSTOM_PROVIDER_PREFIX = "custom-"
MAX_CUSTOM_PROVIDERS = 24
MAX_MODELS_PER_PROVIDER = 100
MAX_MODEL_ID_LENGTH = 200
MAX_NAME_LENGTH = 80


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


# ---------------------------------------------------------------------------
# Provider views (built-in registry + normalized custom entries)
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug[:48] or "provider"


def _normalize_base_url(raw: Any) -> str:
    url = str(raw or "").strip()
    if not url:
        raise SettingsError("Base URL 不能为空")
    if any(ch.isspace() for ch in url):
        raise SettingsError("Base URL 不能包含空白字符")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SettingsError("Base URL 必须是 http(s)://host[/path] 形式")
    return url.rstrip("/")


def _normalize_models(raw: Any) -> list[str]:
    if isinstance(raw, str):
        items: list[Any] = re.split(r"[\n,]+", raw)
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        raise SettingsError("模型列表必须是字符串或字符串数组")
    models: list[str] = []
    for item in items:
        token = str(item or "").strip()
        if not token:
            continue
        if len(token) > MAX_MODEL_ID_LENGTH:
            raise SettingsError(f"模型名过长（> {MAX_MODEL_ID_LENGTH} 字符）：{token[:32]}…")
        if token not in models:
            models.append(token)
    if not models:
        raise SettingsError("模型列表不能为空（至少填一个模型名）")
    if len(models) > MAX_MODELS_PER_PROVIDER:
        raise SettingsError(f"模型数量过多（> {MAX_MODELS_PER_PROVIDER}）")
    return models


def _normalize_custom_entry(raw: Any) -> dict[str, Any] | None:
    """Normalize one stored entry; invalid entries are dropped (never crash the list)."""
    if not isinstance(raw, dict):
        return None
    provider_id = str(raw.get("id") or "").strip()
    if not provider_id or provider_id in GATEWAYS:
        return None
    try:
        base_url = _normalize_base_url(raw.get("base_url"))
        models = _normalize_models(raw.get("models"))
    except SettingsError:
        return None
    name = str(raw.get("name") or provider_id).strip()[:MAX_NAME_LENGTH] or provider_id
    return {
        "id": provider_id,
        "name": name,
        "base_url": base_url,
        # 明文只留在本机存储；绝不进入 snapshot / API 响应 / 日志。
        "api_key": str(raw.get("api_key") or ""),
        "models": models,
    }


def _custom_public_view(entry: dict[str, Any]) -> dict[str, Any]:
    """Secret-free view for GET/UI: key becomes a configured boolean."""
    return {
        "id": entry["id"],
        "name": entry["name"],
        "base_url": entry["base_url"],
        "models": list(entry["models"]),
        "credential_configured": bool(entry["api_key"].strip()),
    }


def _gateway_provider_config(provider: str) -> dict | None:
    try:
        return gateway_config(provider)
    except Exception:
        return None


def _models_from_config(cfg: dict, purpose: str) -> list[str]:
    """Accept both shapes: built-in ``models`` is purpose-keyed, custom is a flat list."""
    models = cfg.get("models")
    if isinstance(models, list):
        return [str(m) for m in models]
    if isinstance(models, dict):
        return list(models.get(purpose, []))
    return []


def _credential_configured(cfg: dict) -> bool:
    if cfg.get("custom"):
        return bool(str(cfg.get("api_key") or "").strip())
    key_env = cfg.get("key_env")
    return bool(os.environ.get(key_env, "").strip() or _dotenv_get(key_env))


def _secret_values(cfg: dict) -> list[str]:
    if cfg.get("custom"):
        values = [str(cfg.get("api_key") or "")]
    else:
        key_env = cfg.get("key_env")
        values = [os.environ.get(key_env, "").strip(), _dotenv_get(key_env)]
    return [v for v in values if v]


def _all_secret_values() -> list[str]:
    """Every known credential in this process — built-ins and custom entries.

    Redaction is deliberately global: a probe/error detail must never leak any key,
    including one belonging to a *different* provider than the one being probed.
    """
    values: list[str] = []
    for cfg in GATEWAYS.values():
        values.extend(_secret_values(cfg))
    try:
        values.extend(entry["api_key"] for entry in runtime_settings_store()._custom_specs())
    except Exception:
        pass
    try:
        values.extend(str(cfg.get("api_key") or "") for cfg in _gateway_custom_entries().values())
    except Exception:
        pass
    out: list[str] = []
    for value in values:
        token = str(value or "")
        if len(token) >= 4 and token not in out:
            out.append(token)
    return out


def _safe_detail(provider: str, detail: Any) -> str | None:
    if detail is None:
        return None
    text = str(detail)
    cfg = _gateway_provider_config(provider) or {}
    for key in _all_secret_values() + _secret_values(cfg):
        if len(key) >= 4:
            text = text.replace(key, "[redacted]")
    return text[:240]


def _builtin_models(provider: str, purpose: str) -> list[str]:
    return list(GATEWAYS[provider].get("models", {}).get(purpose, []))


def _custom_map(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in entries}


def _valid_channel(purpose: str, channel: dict[str, Any],
                   custom_map: dict[str, dict[str, Any]]) -> bool:
    provider = channel.get("provider")
    model = channel.get("model")
    if not isinstance(provider, str) or not isinstance(model, str):
        return False
    if purpose not in MODEL_PURPOSES:
        return False
    if provider in GATEWAYS:
        return model in _builtin_models(provider, purpose)
    entry = custom_map.get(provider)
    if entry is None:
        return False
    return model in entry["models"]


def _default_channels(provider: str) -> dict[str, dict[str, str]]:
    channels: dict[str, dict[str, str]] = {}
    for purpose in MODEL_PURPOSES:
        configured = os.environ.get(_ENV_MODEL_KEYS[purpose], "").strip()
        supported = _builtin_models(provider, purpose)
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

    # -- raw file access ---------------------------------------------------

    def _read_raw(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
            raw = {}
        return raw if isinstance(raw, dict) else {}

    def _custom_specs(self, raw: dict | None = None) -> list[dict[str, Any]]:
        raw = self._read_raw() if raw is None else raw
        stored = raw.get("custom_providers")
        if not isinstance(stored, list):
            return []
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in stored:
            entry = _normalize_custom_entry(item)
            if entry is None or entry["id"] in seen:
                continue
            seen.add(entry["id"])
            entries.append(entry)
        return entries

    def provider_specs(self) -> dict[str, dict[str, Any]]:
        """Transport-only view consumed by ``eval.gateway`` (includes the key)."""
        return {entry["id"]: dict(entry) for entry in self._custom_specs()}

    def _read_channels(self, raw: dict | None = None,
                       custom_map: dict[str, dict[str, Any]] | None = None
                       ) -> dict[str, dict[str, str]]:
        raw = self._read_raw() if raw is None else raw
        if custom_map is None:
            custom_map = _custom_map(self._custom_specs(raw))
        provider = _safe_active_provider()
        channels = _default_channels(provider)
        stored = raw.get("channels")
        if not isinstance(stored, dict):
            return channels
        for purpose in MODEL_PURPOSES:
            item = stored.get(purpose)
            if not isinstance(item, dict):
                continue
            candidate = {"provider": item.get("provider"), "model": item.get("model")}
            if _valid_channel(purpose, candidate, custom_map):
                channels[purpose] = {
                    "provider": str(candidate["provider"]),
                    "model": str(candidate["model"]),
                }
        return channels

    def resolve(self, purpose: str) -> dict[str, str]:
        if purpose not in MODEL_PURPOSES:
            raise SettingsError(f"未知用途：{purpose}")
        return dict(self._read_channels()[purpose])

    # -- public snapshots --------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        raw = self._read_raw()
        custom_entries = self._custom_specs(raw)
        custom_map = _custom_map(custom_entries)
        channels = self._read_channels(raw, custom_map)
        providers: list[dict[str, Any]] = []
        for provider, config in GATEWAYS.items():
            providers.append({
                "id": provider,
                "name": config.get("label", provider),
                "kind": "builtin",
                "credential_configured": _credential_configured(config),
                "capabilities": {
                    purpose: {"models": _builtin_models(provider, purpose)}
                    for purpose in MODEL_PURPOSES
                },
            })
        for entry in custom_entries:
            models = list(entry["models"])
            providers.append({
                "id": entry["id"],
                "name": entry["name"],
                "kind": "custom",
                "base_url": entry["base_url"],
                "models": models,
                "credential_configured": bool(entry["api_key"].strip()),
                "capabilities": {purpose: {"models": list(models)} for purpose in MODEL_PURPOSES},
            })
        return {
            "purposes": list(MODEL_PURPOSES),
            "purpose_labels": dict(PURPOSE_LABELS),
            "providers": providers,
            "custom_providers": [_custom_public_view(entry) for entry in custom_entries],
            "channels": {
                purpose: {
                    **channels[purpose],
                    "purpose": purpose,
                    "label": PURPOSE_LABELS[purpose],
                }
                for purpose in MODEL_PURPOSES
            },
        }

    # -- channel updates ---------------------------------------------------

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        raw = self._read_raw()
        custom_entries = self._custom_specs(raw)
        custom_map = _custom_map(custom_entries)
        candidate = self._read_channels(raw, custom_map)
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
            if not _valid_channel(purpose, next_channel, custom_map):
                provider = next_channel.get("provider")
                model = next_channel.get("model")
                raise SettingsError(
                    f"用途 {purpose} 不支持 provider/model：{provider!r}/{model!r}"
                )
            candidate[purpose] = next_channel
        self._write(candidate, custom_entries)
        return self.snapshot()

    # -- custom provider CRUD (issue A3) -----------------------------------

    def add_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise SettingsError("供应商配置必须是对象")
        raw = self._read_raw()
        entries = self._custom_specs(raw)
        if len(entries) >= MAX_CUSTOM_PROVIDERS:
            raise SettingsError(f"自定义供应商数量已达上限（{MAX_CUSTOM_PROVIDERS}）")
        name = str(payload.get("name") or "").strip()[:MAX_NAME_LENGTH]
        if not name:
            raise SettingsError("供应商名称不能为空")
        base_url = _normalize_base_url(payload.get("base_url"))
        models = _normalize_models(payload.get("models"))
        provider_id = self._new_provider_id(payload.get("id"), name, entries)
        entry = {
            "id": provider_id,
            "name": name,
            "base_url": base_url,
            "api_key": str(payload.get("api_key") or "").strip(),
            "models": models,
        }
        entries.append(entry)
        self._write(self._read_channels(raw, _custom_map(entries)), entries)
        return {**self.snapshot(), "notice": f"已添加自定义供应商「{name}」。"}

    def update_provider(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise SettingsError("供应商配置必须是对象")
        raw = self._read_raw()
        entries = self._custom_specs(raw)
        entry = next((e for e in entries if e["id"] == provider_id), None)
        if entry is None:
            raise SettingsError(f"未知自定义供应商：{provider_id}")
        old_entries = [dict(e) for e in entries]
        if "name" in payload:
            name = str(payload.get("name") or "").strip()[:MAX_NAME_LENGTH]
            if not name:
                raise SettingsError("供应商名称不能为空")
            entry["name"] = name
        if "base_url" in payload:
            entry["base_url"] = _normalize_base_url(payload.get("base_url"))
        if "models" in payload:
            entry["models"] = _normalize_models(payload.get("models"))
        # API key is write-only: absent/empty keeps the stored secret untouched.
        new_key = str(payload.get("api_key") or "").strip()
        if new_key:
            entry["api_key"] = new_key
        custom_map = _custom_map(entries)
        # A base-url/model edit can invalidate an existing assignment; never persist an
        # invalid channel silently — fall back to the built-in default with a notice.
        before = self._read_channels(raw, _custom_map(old_entries))
        channels = self._read_channels(raw, custom_map)
        reverted = self._diff_reverted(before, channels, provider_id)
        self._write(channels, entries)
        notice = f"已更新自定义供应商「{entry['name']}」。"
        if reverted:
            notice += "原有失效的用途指派已回退默认：" + self._reverted_text(reverted)
        return {**self.snapshot(), "notice": notice, "reverted": reverted}

    def delete_provider(self, provider_id: str) -> dict[str, Any]:
        raw = self._read_raw()
        entries = self._custom_specs(raw)
        entry = next((e for e in entries if e["id"] == provider_id), None)
        if entry is None:
            raise SettingsError(f"未知自定义供应商：{provider_id}")
        remaining = [e for e in entries if e["id"] != provider_id]
        channels = self._read_channels(raw, _custom_map(entries))
        reverted: list[dict[str, str]] = []
        defaults = _default_channels(_safe_active_provider())
        for purpose in MODEL_PURPOSES:
            if channels[purpose]["provider"] == provider_id:
                channels[purpose] = dict(defaults[purpose])
                reverted.append({
                    "purpose": purpose,
                    "label": PURPOSE_LABELS[purpose],
                    "provider": channels[purpose]["provider"],
                    "model": channels[purpose]["model"],
                })
        self._write(channels, remaining)
        if reverted:
            notice = (f"已删除自定义供应商「{entry['name']}」；{len(reverted)} 个用途指派已回退默认："
                      + self._reverted_text(reverted))
        else:
            notice = f"已删除自定义供应商「{entry['name']}」；无用途指派受影响。"
        return {**self.snapshot(), "notice": notice, "reverted": reverted}

    def refresh_provider_models(self, provider_id: str, *,
                                timeout: float = 30.0) -> dict[str, Any]:
        """Optional bonus: GET ``{base_url}/models`` and persist the discovered list."""
        if provider_id in GATEWAYS:
            raise SettingsError(f"{provider_id} 是内置供应商，无需拉取")
        raw = self._read_raw()
        entries = self._custom_specs(raw)
        entry = next((e for e in entries if e["id"] == provider_id), None)
        if entry is None:
            raise SettingsError(f"未知自定义供应商：{provider_id}")
        old_entries = [dict(e) for e in entries]
        # Point the gateway at this store's entries for the live fetch, then restore
        # the process default (runtime path) even on failure.
        configure_custom_providers(lambda: self.provider_specs())
        try:
            try:
                discovered = _gateway_fetch_models(provider_id, timeout=timeout)
            except Exception as exc:  # GatewayError et al — already key-redacted
                raise SettingsError(_safe_detail(provider_id, exc) or "拉取模型失败") from exc
        finally:
            configure_custom_providers(lambda: runtime_settings_store().provider_specs())
        if not discovered:
            raise SettingsError("端点 /models 未返回任何模型")
        entry["models"] = discovered[:MAX_MODELS_PER_PROVIDER]
        custom_map = _custom_map(entries)
        before = self._read_channels(raw, _custom_map(old_entries))
        channels = self._read_channels(raw, custom_map)
        reverted = self._diff_reverted(before, channels, provider_id)
        self._write(channels, entries)
        notice = f"已从端点拉取 {len(entry['models'])} 个模型。"
        if reverted:
            notice += "原有失效的用途指派已回退默认：" + self._reverted_text(reverted)
        return {**self.snapshot(), "notice": notice, "reverted": reverted}

    # -- internals ---------------------------------------------------------

    def _new_provider_id(self, explicit: Any, name: str,
                         entries: list[dict[str, Any]]) -> str:
        taken = {e["id"] for e in entries} | set(GATEWAYS)
        if explicit is not None and str(explicit).strip():
            candidate = str(explicit).strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", candidate):
                raise SettingsError(
                    "供应商 id 只能是小写字母/数字/-/_，且以字母或数字开头"
                )
            if candidate in taken:
                raise SettingsError(f"供应商 id 已存在：{candidate}")
            return candidate
        base = CUSTOM_PROVIDER_PREFIX + _slugify(name)
        candidate = base
        suffix = 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _diff_reverted(self, before: dict[str, dict[str, str]],
                       after: dict[str, dict[str, str]],
                       provider_id: str) -> list[dict[str, str]]:
        """Purposes that were assigned to ``provider_id`` and just lost that assignment."""
        reverted: list[dict[str, str]] = []
        for purpose in MODEL_PURPOSES:
            if before[purpose] == after[purpose]:
                continue
            if before[purpose].get("provider") != provider_id:
                continue
            reverted.append({
                "purpose": purpose,
                "label": PURPOSE_LABELS[purpose],
                "provider": after[purpose]["provider"],
                "model": after[purpose]["model"],
            })
        return reverted

    @staticmethod
    def _reverted_text(reverted: list[dict[str, str]]) -> str:
        return "，".join(
            f"{item['label']} → {item['provider']}/{item['model']}" for item in reverted
        )

    def _write(self, channels: dict[str, dict[str, str]],
               custom_entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        payload = {
            "version": 2,
            "channels": channels,
            "custom_providers": [
                {
                    "id": e["id"],
                    "name": e["name"],
                    "base_url": e["base_url"],
                    "api_key": e["api_key"],
                    "models": list(e["models"]),
                }
                for e in custom_entries
            ],
        }
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            # 文件含明文 key：尽量收窄到属主可读（与 .env 同级安全假设，文档明示）。
            try:
                os.chmod(temp_name, 0o600)
            except OSError:
                pass
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

    cfg = _gateway_provider_config(provider)
    if cfg is None or not _valid_channel(
        purpose, {"provider": provider, "model": model}, _gateway_custom_map()
    ):
        return {"provider": provider, "purpose": purpose, "model": model,
                "status": "request_failed", "detail": "配置无效"}
    if probe is None and not _credential_configured(cfg):
        detail = "未配置 API Key（请在设置页填写）" if cfg.get("custom") else f"未配置 {cfg['key_env']}"
        return {"provider": provider, "purpose": purpose, "model": model,
                "status": "missing_credentials", "detail": detail}
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


def _gateway_custom_entries() -> dict[str, dict[str, Any]]:
    """Custom entries as seen by the transport layer (normalized, includes key)."""
    from eval.gateway import custom_gateway_configs

    return custom_gateway_configs()


def _gateway_custom_map() -> dict[str, dict[str, Any]]:
    """Validation view of the transport-layer custom providers (``models`` per id)."""
    return {
        pid: {"models": _models_from_config(cfg, "")}
        for pid, cfg in _gateway_custom_entries().items()
        if cfg.get("custom")
    }


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


# 把自定义供应商条目接到传输层：gateway 不反向 import 本模块，而是按需拉取本进程
# 当前设置路径下的条目（含 key）。内置供应商不受影响；无来源时网关只认内置。
configure_custom_providers(lambda: runtime_settings_store().provider_specs())


__all__ = [
    "CUSTOM_PROVIDER_PREFIX",
    "LLMSettingsStore",
    "MODEL_PURPOSES",
    "PURPOSE_LABELS",
    "SettingsError",
    "configure_settings_path",
    "probe_channel",
    "resolve_channel",
    "runtime_settings_store",
]
