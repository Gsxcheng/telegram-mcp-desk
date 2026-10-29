"""Main window (status, connection info, log, settings) and the tray icon."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core import supervisor
from ..core.config import client_snippets, endpoint_from_env
from ..core.envfile import EnvFile
from ..core.proxy import ProxyConfig
from ..core.settings import UPSTREAM_REPO, Settings
from . import flows
from .common import app_icon, open_path, state_icon
from .login_widget import LoginWidget
from .processes import ServerController
from .proxy_widget import ProxyWidget

ABOUT = (
    f"<p><b>TGMCP Desk {__version__}</b>（非官方）</p>"
    f"<p>chigwell/telegram-mcp 的桌面管理器：安装、登录、选择聊天白名单、工具权限、启动停止和日志。"
    f"与 Telegram 公司及 <a href='https://github.com/{UPSTREAM_REPO}'>{UPSTREAM_REPO}</a> 没有隶属关系；"
    "通过 Telegram API 工作。</p>"
    "<p>许可证：Apache-2.0。本程序不收集、不上传任何数据。</p>"
)


class LogView(QWidget):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.offset = 0
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(5000)
        self.text.setFont(QFont("Consolas", 9))
        self.follow = QCheckBox("自动滚动到最新")
        self.follow.setChecked(True)
        open_btn = QPushButton("打开日志文件夹")
        open_btn.clicked.connect(lambda: open_path(self.settings.log_dir))
        clear_btn = QPushButton("清空显示")
        clear_btn.clicked.connect(self.text.clear)
        row = QHBoxLayout()
        row.addWidget(self.follow)
        row.addStretch(1)
        row.addWidget(clear_btn)
        row.addWidget(open_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.text, 1)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        # Start near the end of an existing log instead of replaying megabytes.
        try:
            self.offset = max(0, self.settings.log_path.stat().st_size - 64 * 1024)
        except OSError:
            self.offset = 0

    def poll(self) -> None:
        chunk, self.offset = supervisor.read_tail(self.settings.log_path, self.offset)
        if chunk:
            bar = self.text.verticalScrollBar()
            self.text.appendPlainText(chunk.rstrip("\n"))
            if self.follow.isChecked():
                bar.setValue(bar.maximum())


class StatusTab(QWidget):
    def __init__(self, settings: Settings, controller: ServerController):
        super().__init__()
        self.settings = settings
        self.controller = controller
        self.state = QLabel()
        f = self.state.font()
        f.setPointSize(f.pointSize() + 4)
        f.setBold(True)
        self.state.setFont(f)
        self.start_btn = QPushButton("启动")
        self.stop_btn = QPushButton("停止")
        self.restart_btn = QPushButton("重启")
        self.start_btn.clicked.connect(controller.start)
        self.stop_btn.clicked.connect(self._stop)
        self.restart_btn.clicked.connect(controller.restart)
        btns = QHBoxLayout()
        for b in (self.start_btn, self.stop_btn, self.restart_btn):
            btns.addWidget(b)
        btns.addStretch(1)

        self.url = QLineEdit()
        self.url.setReadOnly(True)
        copy_url = QPushButton("复制")
        copy_url.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.url.text()))
        url_row = QHBoxLayout()
        url_row.addWidget(self.url, 1)
        url_row.addWidget(copy_url)

        self.client = QComboBox()
        self.snippet = QPlainTextEdit()
        self.snippet.setReadOnly(True)
        self.snippet.setFont(QFont("Consolas", 9))
        copy_snip = QPushButton("复制配置")
        copy_snip.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.snippet.toPlainText())
        )
        self.client.currentIndexChanged.connect(self._show_snippet)

        conn = QGroupBox("连接（只有本机能访问）")
        cl = QFormLayout(conn)
        cl.addRow("MCP 地址", url_row)
        cl.addRow("客户端", self.client)
        cl.addRow(self.snippet)
        cl.addRow(copy_snip)
        note = QLabel(
            "同一个登录会话同时只能有一个进程使用：不要再让客户端用 stdio 方式另起一份 telegram-mcp。"
            "想在别的电脑或 claude.ai 上用，需要自己加 Cloudflare Tunnel + Access 之类的鉴权，"
            "telegram-mcp 的 HTTP 接口本身没有密码，绝不能直接暴露到公网。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")

        lay = QVBoxLayout(self)
        lay.addWidget(self.state)
        lay.addLayout(btns)
        lay.addWidget(conn, 1)
        lay.addWidget(note)
        controller.stateChanged.connect(self._state)
        self._state(controller.state, controller.state_text)
        self.reload()

    def reload(self) -> None:
        ep = endpoint_from_env(EnvFile.load(self.settings.env_path).as_dict())
        self.url.setText(ep.url)
        current = self.client.currentText()
        self._snippets = client_snippets(ep)
        self.client.blockSignals(True)
        self.client.clear()
        self.client.addItems(list(self._snippets))
        idx = self.client.findText(current)
        self.client.setCurrentIndex(max(0, idx))
        self.client.blockSignals(False)
        self._show_snippet()

    def _show_snippet(self, *_):
        self.snippet.setPlainText(self._snippets.get(self.client.currentText(), ""))

    def _state(self, state: str, text: str) -> None:
        self.state.setText(text)
        self.start_btn.setEnabled(state == "stopped")
        self.stop_btn.setEnabled(state != "stopped")
        self.restart_btn.setEnabled(state != "external")

    def _stop(self) -> None:
        if self.controller.state == "external":
            ok = QMessageBox.question(
                self,
                "停止",
                "端口上的 telegram-mcp 不是本程序启动的（可能是之前在终端里开的）。要结束它吗？",
            )
            if ok == QMessageBox.StandardButton.Yes:
                if not self.controller.stop_external():
                    QMessageBox.information(
                        self, "停止", "没找到可以结束的进程，请在原来的窗口里按 Ctrl+C。"
                    )
            return
        self.controller.stop()


class SettingsTab(QWidget):
    changed = Signal()
    rerunWizard = Signal()

    def __init__(self, settings: Settings, controller: ServerController):
        super().__init__()
        self.settings = settings
        self.controller = controller

        access = QGroupBox("AI 能看到什么")
        self.chats_label = QLabel()
        self.tools_label = QLabel()
        chats_btn = QPushButton("选择频道…")
        tools_btn = QPushButton("工具权限…")
        chats_btn.clicked.connect(self._chats)
        tools_btn.clicked.connect(self._tools)
        al = QFormLayout(access)
        al.addRow(chats_btn, self.chats_label)
        al.addRow(tools_btn, self.tools_label)

        proxy_box = QGroupBox("代理")
        self.proxy = ProxyWidget()
        save_proxy = QPushButton("保存代理并重启")
        save_proxy.clicked.connect(self._save_proxy)
        pl = QVBoxLayout(proxy_box)
        pl.addWidget(self.proxy)
        pl.addWidget(save_proxy, 0, Qt.AlignmentFlag.AlignLeft)

        app_box = QGroupBox("管理器")
        self.auto_restart = QCheckBox("意外退出后 30 秒自动重启（连续 5 次刚启动就退出会停下）")
        self.start_on_launch = QCheckBox("打开本程序时自动启动 telegram-mcp")
        self.auto_restart.toggled.connect(self._save_flags)
        self.start_on_launch.toggled.connect(self._save_flags)
        ml = QVBoxLayout(app_box)
        ml.addWidget(self.auto_restart)
        ml.addWidget(self.start_on_launch)

        maint = QGroupBox("维护")
        relogin = QPushButton("重新登录 Telegram…")
        relogin.clicked.connect(self._relogin)
        wizard = QPushButton("重新运行设置向导")
        wizard.clicked.connect(self.rerunWizard.emit)
        edit_env = QPushButton("用记事本打开 .env")
        edit_env.clicked.connect(lambda: open_path(self.settings.env_path))
        open_dir = QPushButton("打开安装文件夹")
        open_dir.clicked.connect(lambda: open_path(self.settings.install_path))
        diag = QPushButton("导出诊断包（已脱敏）…")
        diag.clicked.connect(lambda: flows.export_diagnostics(self.settings, self))
        grid = QHBoxLayout(maint)
        for b in (relogin, wizard, edit_env, open_dir, diag):
            grid.addWidget(b)

        lay = QVBoxLayout(self)
        lay.addWidget(access)
        lay.addWidget(proxy_box)
        lay.addWidget(app_box)
        lay.addWidget(maint)
        lay.addStretch(1)
        self.reload()

    def reload(self) -> None:
        self.chats_label.setText(flows.allowlist_summary(self.settings))
        self.tools_label.setText(flows.tools_summary(self.settings))
        self.proxy.set_config(ProxyConfig.from_env(EnvFile.load(self.settings.env_path).as_dict()))
        for box, value in (
            (self.auto_restart, self.settings.auto_restart),
            (self.start_on_launch, self.settings.start_server_on_launch),
        ):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)

    def _chats(self) -> None:
        flows.edit_chats(self.settings, self.controller, self)
        self.reload()
        self.changed.emit()

    def _tools(self) -> None:
        flows.edit_tools(self.settings, self.controller, self)
        self.reload()
        self.changed.emit()

    def _save_proxy(self) -> None:
        cfg = self.proxy.config()
        problems = cfg.validate()
        if problems:
            QMessageBox.warning(self, "代理", "；".join(problems))
            return
        flows.save_env(self.settings, cfg.to_env())
        if self.controller.is_alive():
            self.controller.restart()
        QMessageBox.information(self, "代理", "已保存。")

    def _save_flags(self) -> None:
        self.settings.auto_restart = self.auto_restart.isChecked()
        self.settings.start_server_on_launch = self.start_on_launch.isChecked()
        self.settings.save()

    def _relogin(self) -> None:
        session = self.settings.install_path / (
            (
                EnvFile.load(self.settings.env_path).get("TELEGRAM_SESSION_NAME")
                or "telegram_session"
            )
            + ".session"
        )
        ok = QMessageBox.question(
            self,
            "重新登录",
            "会暂停 telegram-mcp，把当前登录会话改名备份（.session.bak），然后重新输入手机号和验证码。继续吗？\n\n"
            "旧设备记得在手机 Telegram「设置 → 设备」里移除。",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        was_running = flows.pause_server(self.controller)
        if session.exists():
            session.replace(session.with_name(session.name + ".bak"))
        from PySide6.QtWidgets import QDialog

        dlg = QDialog(self)
        dlg.setWindowTitle("重新登录 Telegram")
        dlg.resize(520, 300)
        login = LoginWidget(self.settings)
        lay = QVBoxLayout(dlg)
        lay.addWidget(login)
        login.loggedIn.connect(lambda _me: QTimer.singleShot(1200, dlg.accept))
        QTimer.singleShot(0, login.start)
        dlg.exec()
        login.cancel()
        if was_running:
            self.controller.start()


class MainWindow(QMainWindow):
    rerunWizard = Signal()
    quitRequested = Signal()

    def __init__(self, settings: Settings, controller: ServerController):
        super().__init__()
        self.settings = settings
        self.controller = controller
        self.setWindowTitle("TGMCP Desk（非官方）")
        self.setWindowIcon(app_icon())
        self.resize(860, 640)
        self.tabs = QTabWidget()
        self.status_tab = StatusTab(settings, controller)
        self.settings_tab = SettingsTab(settings, controller)
        self.settings_tab.rerunWizard.connect(self.rerunWizard.emit)
        self.settings_tab.changed.connect(self.status_tab.reload)
        self.log_tab = LogView(settings)
        about = QLabel(ABOUT)
        about.setWordWrap(True)
        about.setOpenExternalLinks(True)
        about.setAlignment(Qt.AlignmentFlag.AlignTop)
        about_w = QWidget()
        QVBoxLayout(about_w).addWidget(about)
        self.tabs.addTab(self.status_tab, "状态与连接")
        self.tabs.addTab(self.log_tab, "日志")
        self.tabs.addTab(self.settings_tab, "设置")
        self.tabs.addTab(about_w, "关于")
        self.setCentralWidget(self.tabs)

    def reload(self) -> None:
        self.status_tab.reload()
        self.settings_tab.reload()

    def show_log(self) -> None:
        self.tabs.setCurrentWidget(self.log_tab)
        self.bring_to_front()

    def bring_to_front(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.quitRequested.emit()  # no tray to come back from
            event.accept()
            return
        event.ignore()
        self.hide()


class Tray(QSystemTrayIcon):
    quitRequested = Signal()

    def __init__(self, settings: Settings, controller: ServerController, window: MainWindow):
        super().__init__(state_icon("stopped"))
        self.settings = settings
        self.controller = controller
        self.window = window
        menu = QMenu()
        self.status = QAction("状态：已停止", menu)
        self.status.setEnabled(False)
        menu.addAction(self.status)
        menu.addSeparator()
        menu.addAction("打开主窗口", window.bring_to_front)
        self.a_start = menu.addAction("启动", controller.start)
        self.a_stop = menu.addAction("停止", controller.stop)
        menu.addAction("重启", controller.restart)
        menu.addSeparator()
        menu.addAction("选择频道…", self._chats)
        menu.addAction("工具权限…", self._tools)
        menu.addAction("查看日志", window.show_log)
        menu.addAction("打开安装文件夹", lambda: open_path(settings.install_path))
        menu.addSeparator()
        self.a_auto = menu.addAction("意外退出后自动重启")
        self.a_auto.setCheckable(True)
        self.a_auto.setChecked(settings.auto_restart)
        self.a_auto.toggled.connect(self._auto)
        menu.addSeparator()
        menu.addAction("退出（并停止服务）", self.quitRequested.emit)
        self.menu = menu
        self.setContextMenu(menu)
        self.activated.connect(self._activated)
        controller.stateChanged.connect(self._state)
        controller.notify.connect(self._notify)
        self._state(controller.state, controller.state_text)

    def _activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.window.bring_to_front()

    def _state(self, state: str, text: str) -> None:
        key = {"waiting": "starting", "external": "running"}.get(state, state)
        self.setIcon(state_icon(key))
        self.setToolTip(f"TGMCP Desk：{text}"[:63])
        self.status.setText(f"状态：{text}")
        self.a_start.setEnabled(state == "stopped")
        self.a_stop.setEnabled(state != "stopped")

    def _notify(self, message: str, level: str) -> None:
        icon = {
            "warning": QSystemTrayIcon.MessageIcon.Warning,
            "error": QSystemTrayIcon.MessageIcon.Critical,
        }.get(level, QSystemTrayIcon.MessageIcon.Information)
        self.showMessage("TGMCP Desk", message, icon, 5000)

    def _auto(self, on: bool) -> None:
        self.settings.auto_restart = on
        self.settings.save()
        self.window.settings_tab.reload()

    def _chats(self) -> None:
        flows.edit_chats(self.settings, self.controller, None)
        self.window.reload()

    def _tools(self) -> None:
        flows.edit_tools(self.settings, self.controller, None)
        self.window.reload()
