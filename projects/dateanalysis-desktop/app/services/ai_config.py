"""W11 AI default config loader (pure, no Qt).

Priority (high to low):
1) Caller-supplied / QSettings user values (out of scope here)
2) ~/.codex/config.toml openai_base_url / model (tomllib, py3.11+)
3) Env vars OPENAI_BASE_URL / OPENAI_API_BASE / OPENAI_MODEL
4) Fallback: https://api.openai.com/v1 , gpt-4o-mini

api_key only from OPENAI_API_KEY env var; never from codex config.
Parse failures silently fall back; never raise.
"""
from __future__ import annotations

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
