"""W8b/W11 AI client (OpenAI-compatible chat/completions, stdlib urllib)."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse


class AIClientError(Exception):
    """AIClient unified exception; message NEVER contains API Key."""


_CONN_ERR_KEYWORDS = (
    "refused", "getaddrinfo", "no route", "timed out", "timeout",
    "name or service not known", "connection aborted", "connection reset",
    "network is unreachable", "forbidden",
)


def _host_of(url: str) -> str:
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


class AIClient:
    PRESETS: dict[str, dict[str, str]] = {
        "openai": {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini"},
        "deepseek": {"base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
    }

    def __init__(
        self,
        provider: str = "openai",
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.provider = provider or "openai"
        preset = self.PRESETS.get(self.provider)
        if self.provider == "custom":
            self.base_url = (base_url or "").rstrip("/")
            self.model = model or ""
        else:
            if preset is None:
                raise AIClientError(f"未知的提供商：{provider}")
            # W9/W11: caller-supplied base_url/model wins over preset (supports proxies for all providers)
            self.base_url = (base_url or preset["base_url"]).rstrip("/")
            self.model = model or preset["default_model"]
        self.api_key = api_key or ""
        self.timeout = float(timeout)

    def chat(self, messages: list[dict[str, Any]], temperature: float = 0.3) -> str:
        """POST {base_url}/chat/completions; return content str. Raise AIClientError on failure."""
        if not self.api_key:
            raise AIClientError("API Key 为空")
        if not self.base_url:
            raise AIClientError("Base URL 为空")
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        status: int = 0
        raw: bytes = b""
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.getcode()
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                err_raw = e.read()
                if err_raw:
                    err_json = json.loads(err_raw.decode("utf-8", errors="replace"))
                    if isinstance(err_json, dict):
                        err_obj = err_json.get("error")
                        if isinstance(err_obj, dict):
                            detail = str(err_obj.get("message", ""))
                        elif isinstance(err_obj, str):
                            detail = err_obj
                        else:
                            detail = str(err_json)[:200]
            except Exception:
                detail = ""
            code = e.code
            if code in (401, 403):
                msg = f"鉴权失败（HTTP {code}），请检查 API Key 是否正确"
            elif code == 404:
                msg = (
                    f"接口不存在（HTTP 404），可能是 base_url 路径错误"
                    f"或模型不被代理支持（当前模型：{self.model}）"
                )
            elif code == 429:
                msg = "请求被限流（HTTP 429），稍后重试"
            elif 500 <= code < 600:
                msg = f"服务端错误（HTTP {code}）"
                if detail:
                    msg += f"：{detail[:200]}"
            else:
                msg = f"HTTP {code}"
                if detail:
                    msg += f"：{detail[:200]}"
            raise AIClientError(msg) from e
        except TimeoutError:
            raise AIClientError(
                f"请求超时（{int(self.timeout)}s），请检查网络或 base_url 是否可达"
                f"（{_host_of(self.base_url)}）"
            ) from None
        except socket.timeout:
            raise AIClientError(
                f"请求超时（{int(self.timeout)}s），请检查网络或 base_url 是否可达"
                f"（{_host_of(self.base_url)}）"
            ) from None
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            rname = type(reason).__name__
            rstr = str(reason)
            rlow = rstr.lower()
            is_conn_err = any(k in rlow for k in _CONN_ERR_KEYWORDS)
            if is_conn_err:
                msg = (
                    f"无法连接到 {_host_of(self.base_url)}（{rstr}），"
                    "请检查 base_url 是否在当前网络可达（如内网代理需要连 VPN/办公网）"
                )
            else:
                msg = f"网络错误（{rname}）：{rstr}"
            raise AIClientError(msg) from e
        except Exception as e:  # noqa: BLE001
            raise AIClientError(f"请求失败：{type(e).__name__}") from e

        if status < 200 or status >= 300:
            raise AIClientError(f"HTTP {status}")

        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as e:  # noqa: BLE001
            raise AIClientError("响应 JSON 解析失败") from e

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise AIClientError("响应格式异常，缺少 choices[0].message.content") from e
        if not isinstance(content, str):
            content = str(content)
        return content
