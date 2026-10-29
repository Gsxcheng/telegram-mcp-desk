"""First-run setup wizard."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from ..core import allowlist, config, installer, ports
from ..core.envfile import EnvFile
from ..core.proxy import ProxyConfig
from ..core.settings import DEFAULT_UPSTREAM_TAG, UPSTREAM_REPO, Settings
from . import flows
from .common import open_url, run_in_thread
from .login_widget import LoginWidget
from .processes import ServerController, _qenv
from .proxy_widget import ProxyWidget

DISCLAIMER = (
    "<p><b>TGMCP Desk</b> 是一个<b>非官方</b>的开源工具，帮你在自己电脑上安装、登录和管理 "
    f"<a href='https://github.com/{UPSTREAM_REPO}'>chigwell/telegram-mcp</a>，"
    "让 Claude 等 AI 助手通过 MCP 读取你指定的 Telegram 聊天。"
    "本项目与 Telegram 公司、chigwell/telegram-mcp 都没有隶属关系。</p>"
    "<p>它通过 <b>Telegram API</b> 工作：你需要用自己的手机号在 my.telegram.org 申请自己的 "
    "api_id / api_hash。登录后，Telegram「设置 → 设备」里会多一台设备，随时可以在那里移除。</p>"
    "<p>所有数据（api_hash、登录会话、聊天内容）只保存在这台电脑上，本程序不收集、不上传任何信息。"
    "登录会话文件等同于你账号的钥匙，不要发给任何人。</p>"
    "<p>请遵守 Telegram API 使用条款，例如不得用 Telegram 数据训练 AI 模型。</p>"
)


class WelcomePage(QWizardPage):
    def __init__(self):
        super().__init__()
        self.setTitle("欢迎")
        text = QLabel(DISCLAIMER)
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        self.agree = QCheckBox("我已了解，继续")
        self.agree.toggled.connect(self.completeChanged)
        lay = QVBoxLayout(self)
        lay.addWidget(text)
        lay.addStretch(1)
        lay.addWidget(self.agree)

    def isComplete(self) -> bool:
        return self.agree.isChecked()


class InstallPage(QWizardPage):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setTitle("安装 telegram-mcp")
        self.setSubTitle(
            "从 GitHub 下载固定版本并准备 Python 环境。已经装过的话，选到原来的文件夹即可直接使用。"
        )
        self.dir_edit = QLineEdit(str(settings.install_path))
        browse = QPushButton("选择…")
        browse.clicked.connect(self._browse)
        self.tag_edit = QLineEdit(settings.upstream_tag or DEFAULT_UPSTREAM_TAG)
        self.dl_proxy = QLineEdit(settings.download_proxy)
        self.dl_proxy.setPlaceholderText("可空。例如 http://127.0.0.1:7890（Clash 的混合端口）")
        self.state_label = QLabel()
        self.state_label.setWordWrap(True)
        self.install_btn = QPushButton("开始安装")
        self.install_btn.clicked.connect(self._install)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)

        row = QHBoxLayout()
        row.addWidget(self.dir_edit, 1)
        row.addWidget(browse)
        form = QFormLayout()
        form.addRow("安装文件夹", row)
        form.addRow("telegram-mcp 版本", self.tag_edit)
        form.addRow("下载代理", self.dl_proxy)
        warn = QLabel(
            "注意：不要用 pip install telegram-mcp 或 uvx telegram-mcp 安装，PyPI 上同名的包是另一个项目。"
            "本程序只从 GitHub 的 chigwell/telegram-mcp 下载。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(warn)
        lay.addWidget(self.state_label)
        lay.addWidget(self.install_btn)
        lay.addWidget(self.log, 1)
        self.dir_edit.textChanged.connect(self._refresh)
        self._busy = False
        self._proc: QProcess | None = None

    def initializePage(self) -> None:
        self._refresh()

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择安装文件夹", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def target(self) -> Path:
        return Path(self.dir_edit.text().strip()).expanduser()

    def _refresh(self) -> None:
        st = installer.inspect_dir(self.target())
        uv = installer.find_uv(self.settings.uv_path)
        lines = [f"uv：{'已找到 ' + str(uv) if uv else '未安装（安装时会自动下载）'}"]
        if st.is_upstream and st.has_venv:
            lines.append(
                "这个文件夹里已经有可用的 telegram-mcp，可以直接下一步（也可以点按钮重新同步环境）。"
            )
            self.install_btn.setText("重新同步环境")
        elif st.is_upstream:
            lines.append("找到了 telegram-mcp 源码，但还没有 Python 环境，点按钮准备环境。")
            self.install_btn.setText("准备环境")
        elif st.exists and not st.empty:
            lines.append("⚠ 这个文件夹不是空的，也不是 telegram-mcp，请换一个空文件夹。")
            self.install_btn.setText("开始安装")
        else:
            lines.append("将下载 telegram-mcp 到这个文件夹。")
            self.install_btn.setText("开始安装")
        if st.has_session:
            lines.append("检测到已有登录会话文件，会继续使用。")
        self.state_label.setText("\n".join(lines))
        self.install_btn.setEnabled(
            not self._busy and not (st.exists and not st.empty and not st.is_upstream)
        )
        self.completeChanged.emit()

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text.rstrip())

    def _install(self) -> None:
        target = self.target()
        tag = self.tag_edit.text().strip() or DEFAULT_UPSTREAM_TAG
        proxy = self.dl_proxy.text().strip()
        st = installer.inspect_dir(target)
        self._busy = True
        self.install_btn.setEnabled(False)

        def work(progress):
            uv = installer.find_uv(self.settings.uv_path)
            if uv is None:
                progress("正在下载 uv …")
                uv = installer.install_uv(proxy)
                progress(f"uv 已安装：{uv}")
            if not st.is_upstream or st.managed:
                if st.is_upstream and st.managed and st.tag == tag:
                    progress(f"已是 {tag}，跳过下载。")
                else:
                    url = installer.source_archive_url(tag)
                    progress(f"正在下载 {url} …")
                    data = installer.download(url, proxy=proxy)
                    progress(f"下载完成（{len(data) // 1024} KB），正在解压…")
                    installer.install_source(data, target, tag)
            return uv

        def done(uv):
            self.settings.uv_path = str(uv)
            self.settings.install_dir = str(target)
            self.settings.upstream_tag = tag
            self.settings.download_proxy = proxy
            self.settings.save()
            self._run_uv_sync(uv, target, proxy)

        run_in_thread(work, done, self._failed, lambda msg: self._append(str(msg)))

    def _run_uv_sync(self, uv: Path, target: Path, proxy: str) -> None:
        cmd = installer.uv_sync_command(uv)
        self._append("$ " + " ".join(cmd[1:]))
        proc = QProcess(self)
        proc.setWorkingDirectory(str(target))
        proc.setProcessEnvironment(_qenv(installer.child_env(proxy)))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.readyReadStandardOutput.connect(
            lambda: self._append(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace"))
        )
        proc.finished.connect(lambda code, _s: self._sync_done(code))
        proc.errorOccurred.connect(lambda _e: self._failed("无法运行 uv：" + proc.errorString()))
        self._proc = proc
        proc.start(cmd[0], cmd[1:])

    def _sync_done(self, code: int) -> None:
        self._busy = False
        if code == 0:
            self._append("✔ 安装完成")
        else:
            self._append(f"✘ uv sync 失败（退出码 {code}）。国内网络可以填上「下载代理」再试。")
        self._refresh()

    def _failed(self, msg: str) -> None:
        self._busy = False
        self._append("✘ " + msg)
        self._refresh()

    def isComplete(self) -> bool:
        if self._busy:
            return False
        st = installer.inspect_dir(self.target())
        python = Settings(install_dir=str(self.target())).venv_python()
        return st.is_upstream and python.is_file()

    def validatePage(self) -> bool:
        self.settings.install_dir = str(self.target())
        self.settings.save()
        return True


class CredentialsPage(QWizardPage):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setTitle("填写 api_id 和 api_hash")
        self.setSubTitle("每个用户都要用自己的。它们只保存在本机的 .env 文件里。")
        steps = QLabel(
            "1. 点下面按钮打开 my.telegram.org，用手机号登录（验证码发到 Telegram 应用里）。<br>"
            "2. 进入 <b>API development tools</b>，随便填一个应用名（不要带 Telegram 字样），创建。<br>"
            "3. 把页面上的 <b>App api_id</b> 和 <b>App api_hash</b> 复制到这里。"
        )
        steps.setWordWrap(True)
        open_btn = QPushButton("打开 my.telegram.org/apps")
        open_btn.clicked.connect(lambda: open_url("https://my.telegram.org/apps"))
        self.api_id = QLineEdit()
        self.api_hash = QLineEdit()
        self.api_hash.setEchoMode(QLineEdit.EchoMode.Password)
        show = QCheckBox("显示")
        show.toggled.connect(
            lambda on: self.api_hash.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        self.error = QLabel()
        self.error.setStyleSheet("color: #c0392b")
        row = QHBoxLayout()
        row.addWidget(self.api_hash, 1)
        row.addWidget(show)
        form = QFormLayout()
        form.addRow("api_id", self.api_id)
        form.addRow("api_hash", row)
        lay = QVBoxLayout(self)
        lay.addWidget(steps)
        lay.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addStretch(1)

    def initializePage(self) -> None:
        env = EnvFile.load(self.settings.env_path)
        if not self.api_id.text():
            self.api_id.setText(env.get("TELEGRAM_API_ID") or "")
        if not self.api_hash.text():
            self.api_hash.setText(env.get("TELEGRAM_API_HASH") or "")

    def validatePage(self) -> bool:
        problems = config.check_api_credentials(self.api_id.text(), self.api_hash.text())
        if problems:
            self.error.setText("；".join(problems))
            return False
        flows.save_env(
            self.settings, config.credential_env(self.api_id.text(), self.api_hash.text())
        )
        return True


class ProxyPage(QWizardPage):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setTitle("网络代理")
        self.setSubTitle("telegram-mcp 连 Telegram 用的代理（登录也会走这里）。")
        self.widget = ProxyWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(self.widget)

    def initializePage(self) -> None:
        env = EnvFile.load(self.settings.env_path).as_dict()
        cfg = ProxyConfig.from_env(env)
        if not cfg.enabled and not env:
            cfg = ProxyConfig("socks5", "127.0.0.1", 7890)
        self.widget.set_config(cfg)

    def validatePage(self) -> bool:
        cfg = self.widget.config()
        problems = cfg.validate()
        if problems:
            QMessageBox.warning(self, "代理", "；".join(problems))
            return False
        if not self.widget.tested_ok:
            ok = QMessageBox.question(self, "代理", "还没有测试连接，确定继续吗？")
            if ok != QMessageBox.StandardButton.Yes:
                return False
        flows.save_env(self.settings, cfg.to_env())
        return True


class LoginPage(QWizardPage):
    def __init__(self, settings: Settings, controller: ServerController):
        super().__init__()
        self.settings = settings
        self.controller = controller
        self.setTitle("登录 Telegram")
        self.setSubTitle("在这里输入手机号和验证码。不需要扫码，也不需要打开代理的 TUN 模式。")
        self.login = LoginWidget(settings, self._before_start)
        self.login.loggedIn.connect(lambda _me: self.completeChanged.emit())
        lay = QVBoxLayout(self)
        lay.addWidget(self.login)

    def initializePage(self) -> None:
        env = EnvFile.load(self.settings.env_path).as_dict()
        flows.save_env(
            self.settings, {**config.base_env(self.port_hint(env), env), **config.device_env(env)}
        )
        if not self.login.logged_in:
            self.login.start()

    @staticmethod
    def port_hint(env: dict[str, str]) -> int:
        try:
            return int(env["MCP_PORT"])
        except (KeyError, ValueError):
            return ports.pick_port()

    def _before_start(self) -> bool:
        flows.pause_server(self.controller)
        return True

    def isComplete(self) -> bool:
        return self.login.logged_in

    def cleanupPage(self) -> None:
        self.login.cancel()


class AccessPage(QWizardPage):
    def __init__(self, settings: Settings, controller: ServerController):
        super().__init__()
        self.settings = settings
        self.controller = controller
        self.setTitle("AI 能看到什么")
        self.setSubTitle("两道限制：聊天白名单（读哪些聊天）+ 工具权限（能做哪些操作）。")
        self.chats_label = QLabel()
        self.tools_label = QLabel()
        chats_btn = QPushButton("选择频道 / 群 / 机器人…")
        tools_btn = QPushButton("调整工具权限…")
        chats_btn.clicked.connect(self._chats)
        tools_btn.clicked.connect(self._tools)
        form = QFormLayout()
        form.addRow(chats_btn, self.chats_label)
        form.addRow(tools_btn, self.tools_label)
        note = QLabel(
            "工具权限默认是推荐设置：只读，并屏蔽通讯录、草稿、聊天文件夹、全局搜索等能看到整个账号的工具。"
            "聊天白名单至少选一个。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addStretch(1)

    def initializePage(self) -> None:
        flows.ensure_tools_policy(self.settings)
        self._refresh()

    def _refresh(self) -> None:
        self.chats_label.setText(flows.allowlist_summary(self.settings))
        self.tools_label.setText(flows.tools_summary(self.settings))
        self.completeChanged.emit()

    def _chats(self) -> None:
        flows.edit_chats(self.settings, self.controller, self, ask=False)
        self._refresh()

    def _tools(self) -> None:
        flows.edit_tools(self.settings, None, self)
        self._refresh()

    def isComplete(self) -> bool:
        env = EnvFile.load(self.settings.env_path)
        return bool(allowlist.parse(env.get(allowlist.ENV_KEY)))


class FinishPage(QWizardPage):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setTitle("完成")
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        auto = QPushButton("自动选一个可用端口")
        auto.clicked.connect(lambda: self.port.setValue(ports.pick_port(self.port.value())))
        self.desktop = QCheckBox("在桌面放一个图标")
        self.startmenu = QCheckBox("在开始菜单放一个图标")
        self.autostart = QCheckBox("开机自动启动（默认关闭）")
        self.start_now = QCheckBox("完成后立即启动 telegram-mcp")
        for w in (self.desktop, self.startmenu, self.start_now):
            w.setChecked(True)
        if sys.platform != "win32":
            for w in (self.desktop, self.startmenu, self.autostart):
                w.setEnabled(False)
                w.setChecked(False)
        row = QHBoxLayout()
        row.addWidget(self.port)
        row.addWidget(auto)
        row.addStretch(1)
        form = QFormLayout()
        form.addRow("本机端口", row)
        info = QLabel(
            "telegram-mcp 只监听 127.0.0.1（只有本机能访问）。启动后在主窗口的「连接」里可以复制 "
            "Claude Code、Cursor、VS Code 等客户端的配置。关闭窗口后程序会留在右下角托盘。"
        )
        info.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.desktop)
        lay.addWidget(self.startmenu)
        lay.addWidget(self.autostart)
        lay.addWidget(self.start_now)
        lay.addWidget(info)
        lay.addStretch(1)

    def initializePage(self) -> None:
        env = EnvFile.load(self.settings.env_path).as_dict()
        self.port.setValue(
            config.endpoint_from_env(env).port if env.get("MCP_PORT") else ports.pick_port()
        )

    def validatePage(self) -> bool:
        port = self.port.value()
        if ports.in_ranges(port, ports.excluded_ranges()):
            QMessageBox.warning(
                self, "端口", f"端口 {port} 在 Windows 保留端口段里，请点「自动选一个可用端口」。"
            )
            return False
        env = EnvFile.load(self.settings.env_path).as_dict()
        flows.save_env(self.settings, config.base_env(port, env))
        for box, kind in (
            (self.desktop, "desktop"),
            (self.startmenu, "programs"),
            (self.autostart, "startup"),
        ):
            if box.isChecked():
                flows.create_shortcut(kind)
        self.settings.setup_done = True
        self.settings.start_server_on_launch = (
            self.start_now.isChecked() or self.settings.start_server_on_launch
        )
        self.settings.save()
        return True


class SetupWizard(QWizard):
    def __init__(self, settings: Settings, controller: ServerController, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("TGMCP Desk 设置向导（非官方）")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(760, 620)
        self.setButtonText(QWizard.WizardButton.NextButton, "下一步")
        self.setButtonText(QWizard.WizardButton.BackButton, "上一步")
        self.setButtonText(QWizard.WizardButton.FinishButton, "完成")
        self.setButtonText(QWizard.WizardButton.CancelButton, "取消")
        self.finish_page = FinishPage(settings)
        for page in (
            WelcomePage(),
            InstallPage(settings),
            CredentialsPage(settings),
            ProxyPage(settings),
            LoginPage(settings, controller),
            AccessPage(settings, controller),
            self.finish_page,
        ):
            self.addPage(page)

    def start_requested(self) -> bool:
        return self.finish_page.start_now.isChecked()
