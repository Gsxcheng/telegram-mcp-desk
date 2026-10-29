"""In-window Telegram login: phone number -> code -> optional 2FA password."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ..core.settings import Settings
from .processes import HelperProcess

PROMPTS = {
    "phone": "手机号（带国家代码，例如 +86 13800000000）",
    "code": "验证码",
    "password": "二步验证密码（Telegram 的「两步验证」密码）",
}
CODE_VIA = {
    "app": "验证码已发到你已登录的 Telegram 应用里（官方账号 Telegram 发来的消息），不是短信。",
    "sms": "验证码已通过短信发送。",
    "call": "Telegram 会打电话告诉你验证码。",
    "other": "请查看 Telegram 发来的验证码。",
}


class LoginWidget(QWidget):
    loggedIn = Signal(dict)

    def __init__(
        self, settings: Settings, before_start: Callable[[], bool] | None = None, parent=None
    ):
        super().__init__(parent)
        self.settings = settings
        self.before_start = before_start
        self.helper: HelperProcess | None = None
        self.field: str | None = None
        self.logged_in = False

        self.status = QLabel(
            "点「开始登录」。会在 Telegram 的「设置 → 设备」里新增一台设备，随时可以在那里移除。"
        )
        self.status.setWordWrap(True)
        self.prompt = QLabel()
        self.input = QLineEdit()
        self.submit = QPushButton("下一步")
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b")
        self.error.setWordWrap(True)
        self.start_btn = QPushButton("开始登录")

        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.submit)

        lay = QVBoxLayout(self)
        lay.addWidget(self.status)
        lay.addWidget(self.prompt)
        lay.addLayout(row)
        lay.addWidget(self.error)
        lay.addWidget(self.start_btn)
        lay.addStretch(1)

        self.start_btn.clicked.connect(self.start)
        self.submit.clicked.connect(self._submit)
        self.input.returnPressed.connect(self._submit)
        self._show_input(False)

    def _show_input(self, on: bool) -> None:
        for w in (self.prompt, self.input, self.submit):
            w.setVisible(on)

    def start(self) -> None:
        if self.helper is not None:
            return
        if self.before_start and not self.before_start():
            return
        self.error.clear()
        self.status.setText("正在启动…")
        self.start_btn.setEnabled(False)
        self.helper = HelperProcess(self.settings, "tg_login.py", self)
        self.helper.event.connect(self._on_event)
        self.helper.finished.connect(self._on_finished)
        self.helper.start()

    def cancel(self) -> None:
        if self.helper is not None:
            self.helper.cancel()

    def _submit(self) -> None:
        if not self.helper or not self.field:
            return
        value = self.input.text().strip()
        if not value:
            return
        self.helper.send({self.field: value})
        self.input.clear()
        self.submit.setEnabled(False)
        self.error.clear()
        self.status.setText("正在验证…")

    def _on_event(self, msg: dict) -> None:
        ev = msg.get("event")
        if ev == "connecting":
            self.status.setText("正在连接 Telegram…（走你设置的代理）")
        elif ev in ("need", "retry"):
            field = msg.get("field", "")
            self.field = field
            self._show_input(True)
            self.submit.setEnabled(True)
            self.prompt.setText(PROMPTS.get(field, field))
            self.input.setEchoMode(
                QLineEdit.EchoMode.Password if field == "password" else QLineEdit.EchoMode.Normal
            )
            if ev == "retry":
                self.error.setText(msg.get("message", ""))
            if field == "code" and ev == "need":
                self.status.setText(CODE_VIA.get(msg.get("via", "other"), CODE_VIA["other"]))
            elif field == "password" and ev == "need":
                hint = msg.get("hint")
                self.status.setText(
                    "这个账号开了两步验证。" + (f"密码提示：{hint}" if hint else "")
                )
            elif field == "phone" and ev == "need":
                self.status.setText("输入手机号后，Telegram 会把验证码发到你的 Telegram 应用里。")
            self.input.setFocus()
        elif ev == "done":
            me = msg.get("me") or {}
            who = me.get("name", "")
            if me.get("username"):
                who += f"（@{me['username']}）"
            prefix = "已经是登录状态" if msg.get("already") else "登录成功"
            self.status.setText(f"✔ {prefix}：{who}")
            self.logged_in = True
            self._show_input(False)
            self.loggedIn.emit(me)
        elif ev == "error":
            self.error.setText(msg.get("message", "登录失败"))
            self._show_input(False)
        elif ev == "cancelled":
            self.status.setText("已取消。")

    def _on_finished(self, _code: int) -> None:
        self.helper = None
        self.field = None
        if not self.logged_in:
            self.start_btn.setEnabled(True)
            self.start_btn.setText("重新开始登录")
            self._show_input(False)
