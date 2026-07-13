"""W12.1 AI锁与超时修复 单测（不依赖 QApplication 的纯逻辑 + offscreen UI smoke）。"""
from __future__ import annotations

import io
import json
import os
import threading
import urllib.error
from unittest import mock

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.ai_client import AIClient, AICancelledError, AIClientError  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def app():
    global _app
    from PySide6.QtWidgets import QApplication  # noqa: WPS433
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    yield _app


# ---------- ai_client 纯逻辑单测 ----------

def test_default_timeout_is_30s():
    c = AIClient("openai", api_key="k")
    assert c.timeout == 30.0
    c2 = AIClient("openai", api_key="k", timeout=10)
    assert c2.timeout == 10.0
    c3 = AIClient("openai", api_key="k", timeout=None)
    assert c3.timeout == 30.0
    c4 = AIClient("openai", api_key="k", timeout=0)
    assert c4.timeout == 30.0
    c5 = AIClient("openai", api_key="k", timeout=-5)
    assert c5.timeout == 30.0
    c6 = AIClient("openai", api_key="k", timeout="abc")
    assert c6.timeout == 30.0


def test_cancel_event_before_request_raises():
    c = AIClient("openai", api_key="k", timeout=2.0)
    evt = threading.Event()
    evt.set()
    with pytest.raises(AICancelledError):
        c.chat([{"role": "user", "content": "hi"}], cancel_event=evt)


def test_cancel_event_after_urlopen_raises(monkeypatch):
    """即使 urlopen 成功返回，如果 cancel_event 已 set，应抛 AICancelledError。"""
    c = AIClient("openai", api_key="k", timeout=2.0)
    body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
    resp = mock.MagicMock()
    resp.getcode.return_value = 200
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False

    evt = threading.Event()
    call_count = {"n": 0}

    def fake_urlopen(req, timeout=None):
        call_count["n"] += 1
        # 在 urlopen 返回前不 set，resp.__enter__ 后立即 set
        evt.set()
        return resp

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(AICancelledError):
            c.chat([{"role": "user", "content": "hi"}], cancel_event=evt)
    assert call_count["n"] == 1


def test_timeout_message_mentions_retry_and_vpn(monkeypatch):
    import socket as _socket
    c = AIClient("openai", api_key="k", timeout=30.0, base_url="https://example.com/v1")

    def fake_urlopen(req, timeout=None):
        raise _socket.timeout("timed out")

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(AIClientError) as ei:
            c.chat([{"role": "user", "content": "hi"}])
    msg = str(ei.value)
    assert "30s" in msg
    assert "重试" in msg
    assert "VPN" in msg or "办公网" in msg
    assert not isinstance(ei.value, AICancelledError)


def test_http_error_does_not_leak_api_key():
    c = AIClient("openai", api_key="sk-secret-zzz-123")

    def fake_urlopen(_req, timeout=None):
        raise urllib.error.HTTPError(
            url="http://x", code=401, msg="Unauthorized", hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"bad"}}'),
        )

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(AIClientError) as ei:
            c.chat([{"role": "user", "content": "hi"}])
    assert "sk-secret-zzz-123" not in str(ei.value)


def test_success_path_still_works(monkeypatch):
    c = AIClient("openai", api_key="k")
    body = json.dumps({"choices": [{"message": {"content": "稳定区建议…"}}]}).encode("utf-8")
    resp = mock.MagicMock()
    resp.getcode.return_value = 200
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    evt = threading.Event()
    with mock.patch("urllib.request.urlopen", return_value=resp):
        out = c.chat([{"role": "user", "content": "hi"}], cancel_event=evt)
    assert out == "稳定区建议…"


# ---------- UI: 停止按钮/状态/回调（offscreen） ----------

def test_panel_has_cancel_button(app):
    from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel
    p = ProcessAnalysisPanel()
    assert hasattr(p, "ai_cancel_btn")
    # 初始禁用
    assert p.ai_cancel_btn.isEnabled() is False


def test_panel_cancel_callback_invoked(app):
    from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel
    p = ProcessAnalysisPanel()
    called = {"n": 0}
    p.set_ai_cancel_callback(lambda: called.__setitem__("n", called["n"] + 1))
    p.set_report_for_test = True  # 伪造有 report
    # 绕过 _emit_ai_insight 的 report 检查：直接手动点击取消之前要先手动置为 running
    # 我们直接 _on_ai_cancel_clicked 验证回调触发
    p._on_ai_cancel_clicked()
    assert called["n"] == 1
    assert "已请求停止" in p.ai_status_label.text()


def test_set_ai_finished_re_enables_generate_and_disables_cancel(app):
    from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel
    p = ProcessAnalysisPanel()
    # 模拟一次完成：先把按钮状态置成请求中
    p._ai_running = True
    p.ai_cancel_btn.setEnabled(True)
    p.ai_generate_btn.setEnabled(False)
    p.ai_regenerate_btn.setEnabled(False)
    # 没 report / 没 key 时刷新后仍应 disabled
    p.set_ai_finished()
    assert p.ai_cancel_btn.isEnabled() is False
    assert p._ai_running is False
