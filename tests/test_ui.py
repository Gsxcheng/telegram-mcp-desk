"""Headless (offscreen) tests for the Qt layer: dialogs, process control, helper runner."""

import os
import socket
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tgmcp_desk.core.allowlist import Dialog  # noqa: E402
from tgmcp_desk.core.settings import Settings  # noqa: E402
from tgmcp_desk.core.toolscan import ToolInfo  # noqa: E402

FAKES = Path(__file__).resolve().parent / "fakes"

FAKE_SERVER = """
import os, socket, sys, time
port = None
for line in open('.env', encoding='utf-8'):
    if line.startswith('MCP_PORT='):
        port = int(line.split('=', 1)[1])
if os.path.exists('crash'):
    print('crashing on purpose', flush=True)
    sys.exit(3)
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('127.0.0.1', port))
s.listen()
print('listening', port, flush=True)
while True:
    c, _ = s.accept()
    c.close()
"""


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    monkeypatch.setenv("TGMCP_DESK_HOME", str(tmp_path / "home"))
    install = tmp_path / "tm"
    install.mkdir()
    port = free_port()
    (install / ".env").write_text(
        "TELEGRAM_API_ID=123456\nTELEGRAM_API_HASH=0123456789abcdef0123456789abcdef\n"
        f"MCP_PORT={port}\n",
        encoding="utf-8",
    )
    (install / "main.py").write_text(FAKE_SERVER, encoding="utf-8")
    settings = Settings(install_dir=str(install), setup_done=True)
    monkeypatch.setattr(Settings, "venv_python", lambda self: Path(sys.executable))
    return settings, port


def test_chat_picker(app):
    from tgmcp_desk.ui.chat_picker import ChatPickerDialog

    dialogs = [
        Dialog("-1001111111111", "Fake Channel", "channel", "fake_channel"),
        Dialog("555", "Fake Person", "user"),
    ]
    dlg = ChatPickerDialog(dialogs, ["@fake_channel", "@left_chat"], None)
    # Private chats are hidden unless checked; the orphan row is kept and checked.
    assert dlg.tree.topLevelItemCount() == 2
    assert dlg.selected_tokens() == ["-1001111111111", "@left_chat"]
    dlg.show_private.setChecked(True)
    assert dlg.tree.topLevelItemCount() == 3
    person = next(
        dlg.tree.topLevelItem(i)
        for i in range(dlg.tree.topLevelItemCount())
        if dlg.tree.topLevelItem(i).text(0) == "Fake Person"
    )
    person.setCheckState(0, Qt.CheckState.Checked)
    assert "555" in dlg.selected_tokens()
    dlg.search.setText("channel")
    assert dlg.tree.topLevelItemCount() == 1


def test_tools_dialog_defaults_to_privacy_preset(app):
    from tgmcp_desk.ui.tools_dialog import ToolsDialog

    tools = [
        ToolInfo("list_chats", "chats", True),
        ToolInfo("list_contacts", "contacts", True),
        ToolInfo("send_message", "messages", False),
    ]
    dlg = ToolsDialog(tools, None, None)
    assert dlg.selected() == {"list_chats"}
    dlg._accept()
    assert str(dlg.result_policy) == "read-only-list_contacts"

    dlg = ToolsDialog(tools, "read-only", None)
    assert dlg.selected() == {"list_chats", "list_contacts"}
    dlg = ToolsDialog(tools, "read-only+nope", None)  # invalid -> preset
    assert dlg.selected() == {"list_chats"} and dlg.parse_note


def test_controller_start_stop(app, fake_install):
    from tgmcp_desk.ui.processes import ServerController

    settings, port = fake_install
    c = ServerController(settings)
    c.start()
    assert wait_until(lambda: c.state == "running"), c.state_text
    assert str(port) in c.state_text
    c.stop()
    assert wait_until(lambda: c.state == "stopped")
    log = settings.log_path.read_text(encoding="utf-8")
    assert "listening" in log and "[管理器] 启动" in log and "[管理器] 停止" in log


def test_controller_schedules_restart_after_crash(app, fake_install):
    from tgmcp_desk.ui.processes import ServerController

    settings, _ = fake_install
    (settings.install_path / "crash").write_text("")
    c = ServerController(settings)
    notes = []
    c.notify.connect(lambda m, lvl: notes.append((lvl, m)))
    c.start()
    assert wait_until(lambda: c._restart_timer.isActive())
    assert c.state == "starting" and "等待重启" in c.state_text
    assert notes and notes[-1][0] == "warning"
    c.stop()
    assert not c._restart_timer.isActive() and c.state == "stopped"


def test_controller_refuses_busy_port(app, fake_install):
    from tgmcp_desk.ui.processes import ServerController

    settings, port = fake_install
    s = socket.socket()
    s.bind(("127.0.0.1", port))
    s.listen()
    try:
        c = ServerController(settings)
        notes = []
        c.notify.connect(lambda m, lvl: notes.append(m))
        c.start()
        assert not c.is_alive() and c.state == "external"
        assert notes and str(port) in notes[0]
    finally:
        s.close()


def test_helper_process_relays_events(app, fake_install, monkeypatch):
    from tgmcp_desk.ui.processes import HelperProcess

    settings, _ = fake_install
    monkeypatch.setenv("PYTHONPATH", str(FAKES))
    monkeypatch.setenv("FAKE_TG_AUTHORIZED", "1")
    h = HelperProcess(settings, "tg_dialogs.py")
    events, finished = [], []
    h.event.connect(events.append)
    h.finished.connect(finished.append)
    h.start()
    assert wait_until(lambda: finished)
    assert finished == [0]
    assert events[-1]["event"] == "dialogs" and len(events[-1]["dialogs"]) == 5


def test_helper_process_without_install(app, tmp_path):
    from tgmcp_desk.ui.processes import HelperProcess

    h = HelperProcess(Settings(install_dir=str(tmp_path / "none")), "tg_dialogs.py")
    events = []
    h.event.connect(events.append)
    h.start()
    assert events[0]["kind"] == "not_installed"


def test_main_window_and_wizard_build(app, fake_install):
    from tgmcp_desk.ui.main_window import MainWindow, Tray
    from tgmcp_desk.ui.processes import ServerController
    from tgmcp_desk.ui.wizard import SetupWizard

    settings, port = fake_install
    c = ServerController(settings)
    w = MainWindow(settings, c)
    Tray(settings, c, w)
    assert w.status_tab.url.text() == f"http://127.0.0.1:{port}/mcp"
    assert f"127.0.0.1:{port}/mcp" in w.status_tab.snippet.toPlainText()
    assert "未设置" in w.settings_tab.chats_label.text()
    wiz = SetupWizard(settings, c)
    assert len(wiz.pageIds()) == 7
