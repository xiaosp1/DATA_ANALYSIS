"""W8b AI 解读单测（offscreen）。"""
from __future__ import annotations

import io
import json
import os
import urllib.error
from unittest import mock

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    yield _app


from app.services.ai_client import AIClient, AIClientError  # noqa: E402
from app.services.ai_prompt import build_insight_prompt  # noqa: E402
from app.ui.widgets.process_analysis_panel import ProcessAnalysisPanel  # noqa: E402


RAW_SENTINEL = "__RAW_ROW_WO_0815__"


def _synthetic_report() -> dict:
    return {
        "summary": {
            "3": {"count": 20, "pct": 0.10, "unreliable": True},
            "4": {"count": 120, "pct": 0.60, "unreliable": False},
            "5": {"count": 60, "pct": 0.30, "unreliable": False},
        },
        "univariate": {
            "4": {
                "count": 120,
                "unreliable": False,
                "features": {
                    "虎口距": {"count": 120, "mean": 380.0, "std": 8.0,
                              "window_1sigma": (372.0, 388.0), "p5": 368.0, "p95": 392.0},
                    "中指距": {"count": 120, "mean": 1020.0, "std": 10.0,
                              "window_1sigma": (1010.0, 1030.0), "p5": 1005.0, "p95": 1035.0},
                },
            },
            "5": {
                "count": 60,
                "unreliable": False,
                "features": {
                    "虎口距": {"count": 60, "mean": 430.0, "std": 12.0,
                             "window_1sigma": (418.0, 442.0), "p5": 410.0, "p95": 448.0},
                    "中指距": {"count": 60, "mean": 1000.0, "std": 12.0,
                             "window_1sigma": (988.0, 1012.0), "p5": 980.0, "p95": 1020.0},
                },
            },
        },
        "rules": {
            "4": [
                {"conditions": [{"feature": "虎口距", "op": "<=", "threshold": 400.0}],
                 "support": 110, "precision": 0.92, "recall": 0.85, "state": 4},
                {"conditions": [{"feature": "中指距", "op": ">", "threshold": 1010.0}],
                 "support": 100, "precision": 0.80, "recall": 0.70, "state": 4},
                {"conditions": [{"feature": "虎口距", "op": "<=", "threshold": 395.0}],
                 "support": 90, "precision": 0.95, "recall": 0.60, "state": 4},
            ],
            "5": [
                {"conditions": [{"feature": "虎口距", "op": ">", "threshold": 415.0}],
                 "support": 55, "precision": 0.88, "recall": 0.80, "state": 5},
            ],
        },
        "feature_importance": [("虎口距", 120.5), ("中指距", 45.2), ("小指标", 3.1)],
        "meta": {
            "n_rows": 200,
            "n_cols": 5,
            "time_col": "时间",
            "state_col": "指数-s",
            "feature_cols": ["虎口距", "中指距", "小指标"],
            "target_states": ["4", "5"],
            "warnings": ["状态 3 仅 20 条样本（<30），结论不可靠。"],
        },
        # 伪造的原始数据标识，prompt 中绝对不能出现
        "_raw_row": RAW_SENTINEL,
    }


def test_build_prompt_structure():
    msgs = build_insight_prompt(_synthetic_report())
    assert isinstance(msgs, list)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "中文" in msgs[0]["content"]
    user = msgs[1]["content"]
    for kw in ["工艺窗口", "指数", "虎口距", "规则"]:
        assert kw in user
    # 不应包含 df 字样或明显原始数据引用
    assert "df" not in user.lower()
    assert "DataFrame" not in user


def test_prompt_no_raw_data():
    rpt = _synthetic_report()
    rpt["raw_row_value"] = RAW_SENTINEL
    msgs = build_insight_prompt(rpt)
    assert RAW_SENTINEL not in msgs[0]["content"]
    assert RAW_SENTINEL not in msgs[1]["content"]
    assert "200" in msgs[1]["content"]  # 聚合数值允许


def test_ai_client_preset_urls():
    a = AIClient("openai", api_key="x")
    assert a.base_url == "https://api.openai.com/v1"
    assert a.model == "gpt-4o-mini"
    b = AIClient("deepseek", api_key="x")
    assert b.base_url == "https://api.deepseek.com/v1"
    assert b.model == "deepseek-chat"


def test_ai_client_custom():
    c = AIClient("custom", base_url="http://my-proxy:8000/v1", model="my-model", api_key="abc")
    assert c.provider == "custom"
    assert c.base_url == "http://my-proxy:8000/v1"
    assert c.model == "my-model"
    assert c.api_key == "abc"


def test_ai_client_error_handling():
    c = AIClient("openai", api_key="sk-secret-key-xyz-123")

    def fake_urlopen(_req, timeout=None):
        raise urllib.error.URLError("boom")

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(AIClientError) as ei:
            c.chat([{"role": "user", "content": "hi"}])
        msg = str(ei.value)
        assert "网络错误" in msg
        # 不得泄露 key
        assert "sk-secret-key-xyz-123" not in msg


def test_ai_client_http_error_no_key_leak():
    c = AIClient("openai", api_key="sk-secret-abc")

    def fake_urlopen(_req, timeout=None):
        raise urllib.error.HTTPError(
            url="http://x", code=401, msg="Unauthorized", hdrs=None, fp=io.BytesIO(b'{"error":{"message":"bad key"}}')
        )

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(AIClientError) as ei:
            c.chat([{"role": "user", "content": "hi"}])
        assert "sk-secret-abc" not in str(ei.value)
        assert "HTTP 401" in str(ei.value)


def test_ai_client_success_parses_content():
    c = AIClient("openai", api_key="k")
    body = json.dumps({"choices": [{"message": {"content": "稳定区建议…"}}]}).encode("utf-8")
    resp = mock.MagicMock()
    resp.getcode.return_value = 200
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    with mock.patch("urllib.request.urlopen", return_value=resp):
        out = c.chat([{"role": "user", "content": "hi"}])
    assert out == "稳定区建议…"


def test_api_key_obfuscate(app, tmp_path, monkeypatch):
    # 用独立 QSettings 文件隔离测试
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # 选一个独立的 organization/application 以免污染用户真实配置
    from PySide6.QtCore import QSettings as _QS
    s = _QS("DateAnalysis", "DateAnalysis")
    # 直接用 panel 的静态方法验证混淆
    original = "sk-test-key-9981"
    obf = ProcessAnalysisPanel._obfuscate(original)
    assert obf != original
    assert obf  # 非空
    # 写->读
    s.setValue("ai_api_key_openai", obf)
    stored = s.value("ai_api_key_openai", "", type=str)
    assert stored != original  # QSettings 中不是明文
    assert ProcessAnalysisPanel._deobfuscate(stored) == original
    s.remove("ai_api_key_openai")


def test_panel_ai_tab_exists(app):
    p = ProcessAnalysisPanel()
    found = False
    for i in range(p.result_tabs.count()):
        if p.result_tabs.tabText(i) == "AI 解读":
            found = True
            break
    assert found, "AI 解读 Tab 必须存在"
    assert p.ai_generate_btn.isEnabled() is False
    # 配了 key 但没 report，仍禁用
    p.set_api_key("sk-test")
    assert p.ai_generate_btn.isEnabled() is False
    # 没 key 时 tooltip 提示配置 Key
    p.set_api_key("")
    assert "API Key" in p.ai_generate_btn.toolTip()
