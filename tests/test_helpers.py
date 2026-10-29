"""Drive the helper scripts end to end against the fake Telethon in tests/fakes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HELPERS = Path(__file__).resolve().parent.parent / "src" / "tgmcp_desk" / "helpers"
FAKES = Path(__file__).resolve().parent / "fakes"
ENV_TEXT = (
    "TELEGRAM_API_ID=123456\n"
    "TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
    "TELEGRAM_SESSION_NAME=telegram_session\n"
    "TELEGRAM_PROXY_TYPE=socks5\nTELEGRAM_PROXY_HOST=127.0.0.1\nTELEGRAM_PROXY_PORT=7897\n"
)


@pytest.fixture
def install(tmp_path):
    (tmp_path / ".env").write_text(ENV_TEXT, encoding="utf-8")
    return tmp_path


def run_helper(install, script, inputs=(), **env):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith(("TELEGRAM_", "FAKE_TG_"))}
    full_env.update(PYTHONPATH=str(FAKES), PYTHONUTF8="1", **env)
    stdin = "".join(json.dumps(m) + "\n" for m in inputs)
    proc = subprocess.run(
        [sys.executable, str(HELPERS / script)],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=install,
        env=full_env,
        timeout=30,
    )
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, events, proc.stderr


def test_login_phone_code_flow_with_retries(install):
    record = install / "record.json"
    code, events, err = run_helper(
        install,
        "tg_login.py",
        [{"phone": "123"}, {"phone": "+10000000000"}, {"code": "0"}, {"code": "11111"}],
        FAKE_TG_RECORD=str(record),
    )
    assert code == 0, err
    kinds = [(e["event"], e.get("field")) for e in events]
    assert kinds == [
        ("connecting", None),
        ("need", "phone"),
        ("retry", "phone"),
        ("need", "phone"),
        ("need", "code"),
        ("retry", "code"),
        ("need", "code"),
        ("done", None),
    ]
    assert events[4]["via"] == "app"
    assert events[-1]["me"] == {"name": "Test User", "username": "test_user"}
    rec = json.loads(record.read_text())
    assert rec["session"] == str(install / "telegram_session")  # file session, not string
    assert "socks5" in rec["kwargs"]["proxy"] and "7897" in rec["kwargs"]["proxy"]
    # Secrets never appear on stdout.
    out = json.dumps(events)
    assert "11111" not in out and "+10000000000" not in out and "0123456789abcdef" not in out


def test_login_with_2fa(install):
    code, events, err = run_helper(
        install,
        "tg_login.py",
        [{"phone": "+10000000000"}, {"code": "11111"}, {"password": "bad"}, {"password": "pw"}],
        FAKE_TG_2FA="1",
    )
    assert code == 0, err
    fields = [(e["event"], e.get("field")) for e in events]
    assert ("need", "password") in fields and ("retry", "password") in fields
    assert next(e for e in events if e.get("field") == "password")["hint"] == "fake hint"
    assert events[-1]["event"] == "done"
    assert "pw" not in json.dumps(events[:-1]).replace("password", "")


def test_login_already_authorized(install):
    code, events, _ = run_helper(install, "tg_login.py", FAKE_TG_AUTHORIZED="1")
    assert code == 0
    assert events[-1]["event"] == "done" and events[-1]["already"] is True


def test_login_cancel_on_eof(install):
    code, events, _ = run_helper(install, "tg_login.py", [])
    assert code == 0
    assert events[-1]["event"] == "cancelled"


def test_login_offline(install):
    code, events, _ = run_helper(install, "tg_login.py", FAKE_TG_OFFLINE="1")
    assert code == 1
    assert events[-1]["event"] == "error" and events[-1]["kind"] == "network"


def test_login_missing_credentials(tmp_path):
    (tmp_path / ".env").write_text("TELEGRAM_SESSION_NAME=x\n")
    code, events, _ = run_helper(tmp_path, "tg_login.py")
    assert code == 1 and events[-1]["event"] == "error"


def test_dialogs(install):
    code, events, err = run_helper(install, "tg_dialogs.py", FAKE_TG_AUTHORIZED="1")
    assert code == 0, err
    (ev,) = events
    assert ev["event"] == "dialogs"
    kinds = {d["name"]: d["type"] for d in ev["dialogs"]}
    assert kinds == {
        "Fake Channel": "channel",
        "Fake Supergroup": "group",
        "Fake Group": "group",
        "Fake Bot": "bot",
        "Fake Person": "user",
    }
    assert ev["dialogs"][0] == {
        "id": "-1001111111111",
        "name": "Fake Channel",
        "type": "channel",
        "username": "fake_channel",
        "archived": False,
    }


def test_dialogs_not_logged_in(install):
    code, events, _ = run_helper(install, "tg_dialogs.py")
    assert code == 1
    assert events[-1]["kind"] == "not_logged_in"


def test_mtproxy_and_bad_proxy_type(install):
    env = install / ".env"
    env.write_text(
        ENV_TEXT.replace("socks5", "mtproxy") + "TELEGRAM_PROXY_SECRET=ee00\n", encoding="utf-8"
    )
    record = install / "r.json"
    code, events, _ = run_helper(
        install, "tg_login.py", FAKE_TG_AUTHORIZED="1", FAKE_TG_RECORD=str(record)
    )
    assert code == 0
    kw = json.loads(record.read_text())["kwargs"]
    assert "ee00" in kw["proxy"] and "MTProxy" in kw["connection"]

    env.write_text(ENV_TEXT.replace("socks5", "vmess"), encoding="utf-8")
    code, events, _ = run_helper(install, "tg_login.py")
    assert code == 1 and "vmess" in events[-1]["message"]
