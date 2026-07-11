"""W11 tests: ai_config defaults, ProcessAnalysisPanel initial endpoint, AIClient error msg/injection."""
from __future__ import annotations

import os

# offscreen must be set BEFORE any PySide6 import
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = None


@pytest.fixture(scope="module")
def qapp():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    yield _app


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    # Use IniFormat in tmp_path so tests never touch real registry/disk config
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    ini_path = tmp_path / "settings.ini"
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # QSettings with IniFormat reads from explicit filename constructed via setPath; simpler:
    # set application/org to unique values and set Path to tmp_path using IniFormat.
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "__W11TestOrg__", "__W11TestApp__")
    s.clear()
    s.sync()
    yield s
    s.clear()
    s.sync()


def test_load_default_from_config_toml(tmp_path, monkeypatch):
    from app.services import ai_config as ac
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    toml_body = chr(10).join([
        "openai_base_url = \"http://10.135.136.21:8317/v1\"",
        "model = \"gpt-5.5\"",
        "",
    ])
    (codex_dir / "config.toml").write_text(toml_body, encoding="utf-8", newline="\n")
    monkeypatch.setattr(ac._P, "home", classmethod(lambda cls: tmp_path))
    for k in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_MODEL", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    cfg = ac.load_default_ai_config()
    assert cfg["base_url"] == "http://10.135.136.21:8317/v1"
    assert cfg["model"] == "gpt-5.5"
    assert cfg["provider"] == "openai"


def test_load_default_falls_back_to_env_when_no_toml(tmp_path, monkeypatch):
    from app.services import ai_config as ac
    codex_dir = tmp_path / ".codex"
    if codex_dir.exists():
        for f in codex_dir.iterdir():
            f.unlink()
        codex_dir.rmdir()
    monkeypatch.setattr(ac._P, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "foo")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = ac.load_default_ai_config()
    assert cfg["base_url"] == "http://example.com/v1"
    assert cfg["model"] == "foo"


def test_process_analysis_panel_initial_endpoint(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings as _QS
    _QS.setDefaultFormat(_QS.Format.IniFormat)
    _QS.setPath(_QS.Format.IniFormat, _QS.Scope.UserScope, str(tmp_path))
    # Monkeypatch at module level before instantiating panel
    import app.ui.widgets.process_analysis_panel as pan_mod
    monkeypatch.setattr(
        pan_mod,
        "load_default_ai_config",
        lambda: {"provider": "openai", "base_url": "http://10.135.136.21:8317/v1", "model": "gpt-5.5", "api_key": ""},
    )
    # Also redirect the panel's internal QSettings to tmp_path ini by patching QSettings ctor used in __init__
    real_qs = _QS
    class _IsolatedQS(real_qs):
        def __init__(self, *args, **kwargs):
            super().__init__(real_qs.Format.IniFormat, real_qs.Scope.UserScope, "__W11TestOrg__", "__W11TestApp__")
    monkeypatch.setattr(pan_mod, "QSettings", _IsolatedQS)
    p = pan_mod.ProcessAnalysisPanel()
    assert p.ai_base_url_edit.text() == "http://10.135.136.21:8317/v1"
    assert p.ai_model_edit.text() == "gpt-5.5"
    assert p.ai_base_url_edit.isReadOnly() is False
    assert p.ai_model_edit.isReadOnly() is False


def test_ai_client_connection_error_message():
    from app.services.ai_client import AIClient, AIClientError
    c = AIClient(provider="openai", base_url="http://127.0.0.1:1/v1", api_key="***", model="m", timeout=0.5)
    with pytest.raises(AIClientError) as ei:
        c.chat([{"role": "user", "content": "hi"}])
    msg = str(ei.value)
    assert ("无法连接" in msg) or ("请求超时" in msg), msg


def test_ai_client_uses_injected_base_url_for_openai():
    from app.services.ai_client import AIClient
    c = AIClient(provider="openai", base_url="http://my-proxy/v1", model="gpt-5.5", api_key="***")
    assert c.base_url == "http://my-proxy/v1"
    assert c.model == "gpt-5.5"
