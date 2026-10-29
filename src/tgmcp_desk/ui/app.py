"""Application entry: single instance, wizard on first run, then tray + main window."""

from __future__ import annotations

import getpass
import hashlib
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QWizard

from ..core.settings import APP_NAME, Settings
from .common import app_icon
from .main_window import MainWindow, Tray
from .processes import ServerController
from .wizard import SetupWizard


def _instance_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return "tgmcp-desk-" + hashlib.sha1(user.encode()).hexdigest()[:10]


def _notify_running_instance(name: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


class DeskApp:
    def __init__(self, app: QApplication):
        self.app = app
        self.settings = Settings.load()
        self.controller = ServerController(self.settings)
        self.window = MainWindow(self.settings, self.controller)
        self.window.rerunWizard.connect(self.run_wizard)
        self.tray = Tray(self.settings, self.controller, self.window)
        self.tray.quitRequested.connect(self.quit)
        self.window.quitRequested.connect(self.quit)
        self.server: QLocalServer | None = None

    def listen(self, name: str) -> None:
        QLocalServer.removeServer(name)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._on_connection)
        self.server.listen(name)

    def _on_connection(self) -> None:
        conn = self.server.nextPendingConnection() if self.server else None
        if conn is not None:
            conn.readyRead.connect(lambda c=conn: (c.readAll(), self.window.bring_to_front()))

    def run_wizard(self) -> bool:
        wizard = SetupWizard(
            self.settings, self.controller, self.window if self.window.isVisible() else None
        )
        wizard.setWindowIcon(app_icon())
        accepted = wizard.exec() == QWizard.DialogCode.Accepted
        if accepted:
            self.window.reload()
            if wizard.start_requested():
                self.controller.start()
        return accepted

    def start(self) -> int:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        if not self.settings.setup_done or not self.settings.venv_python().is_file():
            if not self.run_wizard() and not self.settings.setup_done:
                return 0
        elif self.settings.start_server_on_launch:
            QTimer.singleShot(0, self.controller.start)
        self.window.bring_to_front()
        return self.app.exec()

    def quit(self) -> None:
        self.controller.stop()
        self.tray.hide()
        self.app.quit()


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    name = _instance_name()
    if _notify_running_instance(name):
        return 0
    desk = DeskApp(app)
    desk.listen(name)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.information(
            None, APP_NAME, "系统托盘不可用：关闭主窗口后程序会继续在后台运行。"
        )
    try:
        return desk.start()
    finally:
        desk.controller.stop()
