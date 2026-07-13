"""W8b/W11/W12.1/W12.7 AI client (OpenAI-compatible chat/completions, stdlib urllib)."""
from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse


class AIClientError(Exception):
    """AIClient unified exception; message NEVER contains API Key."""


class AICancelledError(AIClientError):
    """Raised when cancel_event is set before/during request."""


_CONN_ERR_KEYWORDS = (
    "refused", "getaddrinfo", "no route", "timed out", "timeout",
    "name or service not known", "connection aborted", "connection reset",
    "network is unreachable", "forbidden",
)


def _host_of(url):
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise AICancelledError("用户已取消")


class AIClient:
    PRESETS = {
        "openai": {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini"},
        "deepseek": {"base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat"},
    }

    def __init__(self, provider="openai", base_url=None, api_key=None, model=None, timeout=30.0):
        self.provider = provider or "openai"
        preset = self.PRESETS.get(self.provider)
        if self.provider == "custom":
            self.base_url = (base_url or "").rstrip("/")
            self.model = model or ""
        else:
            if preset is None:
                raise AIClientError("未知的提供商：" + str(provider))
            self.base_url = (base_url or preset["base_url"]).rstrip("/")
            self.model = model or preset["default_model"]
        self.api_key = api_key or ""
        try:
            t = float(timeout) if timeout is not None else 30.0
            if t <= 0 or not (t == t):  # 防御：0/None/负数/NaN fallback 到 30s
                t = 30.0
        except (TypeError, ValueError):
            t = 30.0
        self.timeout = t

    def chat(self, messages, temperature=0.3, cancel_event=None):
        _check_cancel(cancel_event)
        if not self.api_key:
            raise AIClientError("API Key 为空")
        if not self.base_url:
            raise AIClientError("Base URL 为空")
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {"model": self.model, "messages": messages, "temperature": float(temperature)}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
        )
        status = 0
        raw = b""
        timeout_hint = ("请求超时（" + str(int(self.timeout)) + "s），可点重试；若多次超时请检查 base_url 是否可达、VPN/办公网是否正常")

        # W12.7: 用 watchdog 线程做硬总超时。
        # urllib 的 timeout 只是每个 socket 操作（connect/read/write）的单次超时，
        # 慢代理分多次小块返回时总耗时可以远超 timeout。watchdog 在 deadline 到了
        # 之后直接关 socket，强制 urlopen/resp.read 抛错，从而保证总时长 ≤ timeout。
        _deadline_event = threading.Event()
        _watchdog: threading.Thread | None = None
        _resp_holder: list[Any] = [None]

        def _watchdog_run():
            if _deadline_event.wait(self.timeout):
                return  # 正常完成，无需触发
            # 超时：关 socket 强制中断
            try:
                resp_obj = _resp_holder[0]
                if resp_obj is not None:
                    # 尝试拿到底层 socket 并 close
                    try:
                        fp = getattr(resp_obj, "fp", None)
                        if fp is not None:
                            raw_sock = getattr(fp, "_sock", None) or getattr(fp, "sock", None)
                            if raw_sock is not None and hasattr(raw_sock, "close"):
                                raw_sock.close()
                    except Exception:
                        pass
                    try:
                        resp_obj.close()
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            _check_cancel(cancel_event)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                _resp_holder[0] = resp
                _watchdog = threading.Thread(target=_watchdog_run, name="AIClientWatchdog", daemon=True)
                _watchdog.start()
                status = resp.getcode()
                raw = resp.read()
            _deadline_event.set()  # 正常完成，通知 watchdog 退出
            if _watchdog is not None:
                _watchdog.join(timeout=1.0)
            _check_cancel(cancel_event)
        except AICancelledError:
            _deadline_event.set()
            if _watchdog is not None:
                try:
                    _watchdog.join(timeout=1.0)
                except Exception:
                    pass
            raise
        except urllib.error.HTTPError as e:
            _deadline_event.set()
            if _watchdog is not None:
                try:
                    _watchdog.join(timeout=1.0)
                except Exception:
                    pass
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
                msg = "鉴权失败（HTTP " + str(code) + "），请检查 API Key 是否正确"
            elif code == 404:
                msg = ("接口不存在（HTTP 404），可能是 base_url 路径错误或模型不被代理支持（当前模型：" + str(self.model) + "）")
            elif code == 429:
                msg = "请求被限流（HTTP 429），稍后重试"
            elif 500 <= code < 600:
                msg = "服务端错误（HTTP " + str(code) + "）"
                if detail:
                    msg += "：" + detail[:200]
            else:
                msg = "HTTP " + str(code)
                if detail:
                    msg += "：" + detail[:200]
            raise AIClientError(msg) from e
        except TimeoutError:
            _deadline_event.set()
            if _watchdog is not None:
                try:
                    _watchdog.join(timeout=1.0)
                except Exception:
                    pass
            raise AIClientError(timeout_hint + "（" + _host_of(self.base_url) + "）") from None
        except socket.timeout:
            _deadline_event.set()
            if _watchdog is not None:
                try:
                    _watchdog.join(timeout=1.0)
                except Exception:
                    pass
            raise AIClientError(timeout_hint + "（" + _host_of(self.base_url) + "）") from None
        except urllib.error.URLError as e:
            _deadline_event.set()
            if _watchdog is not None:
                try:
                    _watchdog.join(timeout=1.0)
                except Exception:
                    pass
            reason = getattr(e, "reason", e)
            rname = type(reason).__name__
            rstr = str(reason)
            rlow = rstr.lower()
            # W12.7: watchdog 触发的 socket close 会表现为 URLError(BadStatusLine/ConnectionReset/...)
            # 统一按超时文案返回
            _watchdog_triggered = (
                _watchdog is not None
                and not _watchdog.is_alive()
            )
            is_timeout_like = (
                _watchdog_triggered
                or "timed out" in rlow
                or "timeout" in rlow
                or "closed" in rlow
                or "broken pipe" in rlow
                or "connection reset" in rlow
            )
            if is_timeout_like:
                msg = timeout_hint + "（" + _host_of(self.base_url) + "）"
            else:
                is_conn_err = any(k in rlow for k in _CONN_ERR_KEYWORDS)
                if is_conn_err:
                    msg = ("无法连接到 " + _host_of(self.base_url) + "（" + rstr + "），请检查 base_url 是否在当前网络可达（如内网代理需要连 VPN/办公网）")
                else:
                    msg = "网络错误（" + rname + "）：" + rstr
            raise AIClientError(msg) from e
        except Exception as e:
            _deadline_event.set()
            if _watchdog is not None:
                try:
                    _watchdog.join(timeout=1.0)
                except Exception:
                    pass
            raise AIClientError("请求失败：" + type(e).__name__) from e

        if status < 200 or status >= 300:
            raise AIClientError("HTTP " + str(status))

        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as e:
            raise AIClientError("响应 JSON 解析失败") from e

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise AIClientError("响应格式异常，缺少 choices[0].message.content") from e
        if not isinstance(content, str):
            content = str(content)
        return content
