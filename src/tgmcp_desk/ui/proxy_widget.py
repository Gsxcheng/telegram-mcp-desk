"""Proxy settings form with local proxy detection and a connection test."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.proxy import ProxyConfig, ProxyTestError, check_proxy, detect_local_proxies
from .common import run_in_thread

TYPE_LABELS = [
    ("none", "不用代理（能直连 Telegram 时）"),
    ("socks5", "SOCKS5（Clash、v2rayN 等，推荐）"),
    ("http", "HTTP"),
    ("socks4", "SOCKS4"),
    ("mtproxy", "MTProxy"),
]


class ProxyWidget(QWidget):
    def __init__(self, cfg: ProxyConfig | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.tested_ok = False
        self.type = QComboBox()
        for key, label in TYPE_LABELS:
            self.type.addItem(label, key)
        self.host = QLineEdit()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.rdns = QCheckBox("由代理解析域名（一般保持勾选）")

        form = QFormLayout()
        form.addRow("类型", self.type)
        form.addRow("地址", self.host)
        form.addRow("端口", self.port)
        form.addRow("用户名（可空）", self.username)
        form.addRow("密码（可空）", self.password)
        form.addRow("MTProxy secret", self.secret)
        form.addRow("", self.rdns)
        self._form = form

        self.detect_btn = QPushButton("自动查找本机代理")
        self.test_btn = QPushButton("测试连接")
        self.result = QLabel()
        self.result.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.detect_btn)
        buttons.addWidget(self.test_btn)
        buttons.addStretch(1)

        hint = QLabel(
            "国内网络一般需要代理。Clash 系列的端口在软件「设置」里能看到（常见 7890 或 7897），"
            "类型选 SOCKS5 即可，不需要打开 TUN 模式。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")

        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addLayout(buttons)
        lay.addWidget(self.result)
        lay.addStretch(1)

        self.type.currentIndexChanged.connect(self._sync_enabled)
        for w in (self.host, self.username, self.password, self.secret):
            w.textChanged.connect(self._changed)
        self.port.valueChanged.connect(self._changed)
        self.type.currentIndexChanged.connect(self._changed)
        self.detect_btn.clicked.connect(self._detect)
        self.test_btn.clicked.connect(self._test)
        self.set_config(cfg or ProxyConfig())

    def set_config(self, cfg: ProxyConfig) -> None:
        idx = self.type.findData(cfg.type)
        self.type.setCurrentIndex(max(0, idx))
        self.host.setText(cfg.host or "127.0.0.1")
        self.port.setValue(cfg.port or 7890)
        self.username.setText(cfg.username)
        self.password.setText(cfg.password)
        self.secret.setText(cfg.secret)
        self.rdns.setChecked(cfg.rdns)
        self._sync_enabled()
        self.tested_ok = False

    def config(self) -> ProxyConfig:
        return ProxyConfig(
            type=self.type.currentData(),
            host=self.host.text().strip(),
            port=self.port.value(),
            username=self.username.text(),
            password=self.password.text(),
            rdns=self.rdns.isChecked(),
            secret=self.secret.text().strip(),
        )

    def _sync_enabled(self) -> None:
        t = self.type.currentData()
        on = t != "none"
        for w in (self.host, self.port):
            w.setEnabled(on)
        for w in (self.username, self.password, self.rdns):
            w.setEnabled(on and t != "mtproxy")
        self.secret.setEnabled(t == "mtproxy")

    def _changed(self, *_):
        self.tested_ok = False
        self.result.clear()

    def _detect(self) -> None:
        self.result.setText("正在查找…")
        self.detect_btn.setEnabled(False)

        def done(found):
            self.detect_btn.setEnabled(True)
            if not found:
                self.result.setText(
                    "本机常见端口上没找到代理。请确认代理软件已打开，或手动填写端口。"
                )
                return
            if self.type.currentData() in ("none", "mtproxy"):
                self.type.setCurrentIndex(self.type.findData("socks5"))
            self.host.setText("127.0.0.1")
            self.port.setValue(found[0])
            others = "、".join(str(p) for p in found[1:])
            extra = f"（另外还有 {others}）" if others else ""
            self.result.setText(f"找到本机端口 {found[0]}{extra}，点「测试连接」确认。")

        run_in_thread(lambda _p: detect_local_proxies(), done, self._fail)

    def _test(self) -> None:
        cfg = self.config()
        self.result.setText("正在测试…")
        self.test_btn.setEnabled(False)

        def done(msg):
            self.test_btn.setEnabled(True)
            self.tested_ok = True
            self.result.setText("✔ " + msg)

        def work(_p):
            try:
                return check_proxy(cfg)
            except ProxyTestError as exc:
                raise RuntimeError(str(exc)) from exc

        run_in_thread(work, done, self._fail)

    def _fail(self, msg: str) -> None:
        self.detect_btn.setEnabled(True)
        self.test_btn.setEnabled(True)
        self.tested_ok = False
        self.result.setText("✘ " + msg)
