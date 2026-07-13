"""W11 AI default config loader (pure, no Qt).

Priority (high to low):
1) Caller-supplied / QSettings user values (out of scope here)
2) ai_config.json in startup working directory (W12.3)
3) ~/.codex/config.toml openai_base_url / model (tomllib, py3.11+)
4) Env vars OPENAI_BASE_URL / OPENAI_API_BASE / OPENAI_MODEL
5) Fallback: https://api.openai.com/v1 , gpt-4o-mini

api_key only from OPENAI_API_KEY env var; never from codex config.
Parse failures silently fall back; never raise.
"""
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path as _P

_PRESET_BASE_URL = "https://api.openai.com/v1"
_PRESET_MODEL = "gpt-4o-mini"


def _load_codex_config():
    bu, md = "", ""
    try:
        p = _P.home() / ".codex" / "config.toml"
        if not p.is_file():
            return "", ""
        with p.open("rb") as f:
            data = tomllib.load(f)
        if isinstance(data, dict):
            v1 = data.get("openai_base_url")
            v2 = data.get("model")
            if isinstance(v1, str) and v1.strip():
                bu = v1.strip().rstrip("/")
            if isinstance(v2, str) and v2.strip():
                md = v2.strip()
    except Exception:
        return "", ""
    return bu, md


def _load_env():
    bu = (os.environ.get("OPENAI_BASE_URL", "") or os.environ.get("OPENAI_API_BASE", "") or "").strip()
    if bu:
        bu = bu.rstrip("/")
    md = (os.environ.get("OPENAI_MODEL", "") or "").strip()
    k = (os.environ.get("OPENAI_API_KEY", "") or "").strip()
    return bu, md, k


def load_default_ai_config():
    t_url, t_model = _load_codex_config()
    e_url, e_model, e_key = _load_env()
    return {
        "provider": "openai",
        "base_url": t_url or e_url or _PRESET_BASE_URL,
        "model": t_model or e_model or _PRESET_MODEL,
        "api_key": e_key,
    }


def load_ai_config_file(path: str | _P) -> dict[str, dict[str, str]]:
    """Load ai_config.json from a path.

    Expected format:
        {
          "providers": {
            "openai":   {"base_url": "...", "model": "...", "api_key": "..."},
            "deepseek": {"base_url": "...", "model": "...", "api_key": "..."}
          }
        }

    Returns a dict of {provider: {base_url, model, api_key}}.
    Missing file / parse error / wrong format → return empty dict, never raise.
    """
    try:
        p = _P(path)
        if not p.is_file():
            return {}
        text = p.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        providers = data.get("providers")
        if not isinstance(providers, dict):
            return {}
        out: dict[str, dict[str, str]] = {}
        for name, info in providers.items():
            if not isinstance(name, str) or not isinstance(info, dict):
                continue
            base_url = info.get("base_url") or ""
            model = info.get("model") or ""
            api_key = info.get("api_key") or ""
            if not isinstance(base_url, str):
                base_url = ""
            if not isinstance(model, str):
                model = ""
            if not isinstance(api_key, str):
                api_key = ""
            out[name] = {
                "base_url": base_url.strip().rstrip("/") if base_url.strip() else "",
                "model": model.strip(),
                "api_key": api_key.strip(),
            }
        return out
    except Exception:
        return {}
