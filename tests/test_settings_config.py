import json

from tgmcp_desk.core.config import (
    Endpoint,
    base_env,
    check_api_credentials,
    client_snippets,
    device_env,
    endpoint_from_env,
)
from tgmcp_desk.core.settings import Settings


def test_settings_roundtrip_ignores_unknown(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(install_dir=str(tmp_path / "tm"), setup_done=True)
    s.save(p)
    raw = json.loads(p.read_text())
    raw["future_field"] = 1
    p.write_text(json.dumps(raw))
    loaded = Settings.load(p)
    assert loaded == s
    assert loaded.env_path == tmp_path / "tm" / ".env"
    assert Settings.load(tmp_path / "missing.json") == Settings()


def test_check_api_credentials():
    assert check_api_credentials("123456", "0123456789abcdef0123456789abcdef") == []
    assert len(check_api_credentials("abc", "short")) == 2


def test_base_env_keeps_existing_session_name():
    assert base_env(18765)["TELEGRAM_SESSION_NAME"] == "telegram_session"
    assert base_env(1, {"TELEGRAM_SESSION_NAME": "mine"})["TELEGRAM_SESSION_NAME"] == "mine"
    assert base_env(18765)["MCP_HOST"] == "127.0.0.1"


def test_device_env():
    assert device_env({}) == {"TELEGRAM_DEVICE_MODEL": "TGMCP Desk"}
    assert device_env({"TELEGRAM_DEVICE_MODEL": "x"}) == {}


def test_endpoint_and_snippets():
    ep = endpoint_from_env({"MCP_HOST": "0.0.0.0", "MCP_PORT": "18765"})
    assert ep == Endpoint("127.0.0.1", 18765)
    assert ep.url == "http://127.0.0.1:18765/mcp"
    snippets = client_snippets(ep)
    assert all(ep.url in v for v in snippets.values())
    assert endpoint_from_env({}).port == 8765
