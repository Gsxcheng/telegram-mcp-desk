"""Actions shared by the wizard, the main window and the tray menu."""

from __future__ import annotations

import io
import os
import platform
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..core import allowlist, ports, redact
from ..core.allowlist import Dialog
from ..core.envfile import EnvFile
from ..core.exposure import privacy_preset
from ..core.installer import inspect_dir
from ..core.settings import Settings
from ..core.toolscan import as_flags, scan_install
from .chat_picker import ChatPickerDialog
from .processes import HelperProcess, ServerController
from .tools_dialog import ToolsDialog

TOOLS_KEY = "TELEGRAM_EXPOSED_TOOLS"


def save_env(settings: Settings, values: dict[str, str | None]) -> None:
    env = EnvFile.load(settings.env_path)
    env.update(values)
    env.save()


def pause_server(controller: ServerController) -> bool:
    """Stop the server (one session can't be shared) and wait for the port to close."""
    was_running = controller.want_running or controller.is_alive()
    controller.stop()
    deadline = time.monotonic() + 10
    port = controller.port()
    while ports.is_listening(port) and time.monotonic() < deadline:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 100)
        time.sleep(0.1)
    return was_running


class BusyDialog(QDialog):
    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("请稍候")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(text))
        bar = QProgressBar()
        bar.setRange(0, 0)
        lay.addWidget(bar)
        self.setMinimumWidth(360)


def fetch_dialogs(settings: Settings, parent: QWidget | None) -> list[Dialog] | None:
    """Run the dialogs helper (server must be stopped). Shows errors itself."""
    helper = HelperProcess(settings, "tg_dialogs.py")
    result: dict = {}
    done = {"finished": False}
    loop = QEventLoop()
    helper.event.connect(lambda msg: result.update(msg))

    def finished(_code: int) -> None:
        done["finished"] = True
        loop.quit()

    helper.finished.connect(finished)
    busy = BusyDialog("正在读取对话列表（一般十几秒）…", parent)
    busy.show()
    helper.start()
    if not done["finished"]:
        loop.exec()
    busy.close()
    if result.get("event") == "dialogs":
        return [
            Dialog(
                str(d.get("id", "")),
                d.get("name", ""),
                d.get("type", "other"),
                d.get("username", ""),
                bool(d.get("archived")),
            )
            for d in result.get("dialogs", [])
        ]
    msg = result.get("message") or "读取失败，详情见日志文件夹里的 helpers.log。"
    QMessageBox.warning(parent, "读取对话列表", msg)
    return None


def edit_chats(
    settings: Settings, controller: ServerController, parent: QWidget | None, ask: bool = True
) -> bool:
    if ask and controller.is_alive():
        ok = QMessageBox.question(
            parent,
            "选择频道",
            "读取对话列表要先暂停 telegram-mcp（十几秒），选完会自动重新启动。继续吗？",
        )
        if ok != QMessageBox.StandardButton.Yes:
            return False
    was_running = pause_server(controller)
    saved = False
    try:
        dialogs = fetch_dialogs(settings, parent)
        if dialogs is None:
            return False
        current = allowlist.parse(EnvFile.load(settings.env_path).get(allowlist.ENV_KEY))
        dlg = ChatPickerDialog(dialogs, current, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            save_env(settings, {allowlist.ENV_KEY: allowlist.format_tokens(dlg.selected_tokens())})
            saved = True
    finally:
        if was_running:
            controller.start()
    return saved


def installed_tools(settings: Settings):
    return scan_install(settings.install_path)


def ensure_tools_policy(settings: Settings) -> None:
    """Apply the privacy preset when no exposure policy is configured yet."""
    env = EnvFile.load(settings.env_path)
    if env.get(TOOLS_KEY):
        return
    tools = installed_tools(settings)
    if tools:
        env.set(TOOLS_KEY, str(privacy_preset(as_flags(tools))))
        env.save()


def edit_tools(
    settings: Settings, controller: ServerController | None, parent: QWidget | None
) -> bool:
    tools = installed_tools(settings)
    if not tools:
        QMessageBox.warning(
            parent, "工具权限", "在安装目录里找不到 telegram-mcp 的工具列表，请先完成安装。"
        )
        return False
    current = EnvFile.load(settings.env_path).get(TOOLS_KEY)
    dlg = ToolsDialog(tools, current, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted or dlg.result_policy is None:
        return False
    save_env(settings, {TOOLS_KEY: str(dlg.result_policy)})
    if controller is not None and controller.is_alive():
        controller.restart()
    return True


def allowlist_summary(settings: Settings) -> str:
    tokens = allowlist.parse(EnvFile.load(settings.env_path).get(allowlist.ENV_KEY))
    return f"已选 {len(tokens)} 个聊天" if tokens else "⚠ 未设置（AI 能读所有聊天）"


def tools_summary(settings: Settings) -> str:
    value = EnvFile.load(settings.env_path).get(TOOLS_KEY)
    if not value or value.strip().lower() == "all":
        return "⚠ 全部工具（包括发消息、删除）"
    tools = installed_tools(settings)
    if not tools:
        return value
    from ..core.exposure import ExposureError, ExposurePolicy

    flags = as_flags(tools)
    try:
        policy = ExposurePolicy.parse(value)
    except ExposureError as exc:
        return f"⚠ 设置有误：{exc}"
    problems = policy.problems(flags)
    if problems:
        return "⚠ " + "；".join(problems)
    exposed = policy.exposed(flags)
    writes = [n for n in exposed if not flags[n]]
    return f"开启 {len(exposed)} 个工具" + (
        f"，含 {len(writes)} 个写入工具" if writes else "，全部只读"
    )


def export_diagnostics(settings: Settings, parent: QWidget | None) -> None:
    default = Path.home() / f"diagnostics-tgmcp-desk-{datetime.now():%Y%m%d-%H%M}.zip"
    path, _ = QFileDialog.getSaveFileName(parent, "保存诊断包", str(default), "Zip (*.zip)")
    if not path:
        return
    env = EnvFile.load(settings.env_path).as_dict()
    state = inspect_dir(settings.install_path)
    info = [
        f"tgmcp-desk {__version__}",
        f"python {sys.version.split()[0]} / {platform.platform()}",
        f"upstream tag: {state.tag or '未知'} managed={state.managed} venv={state.has_venv} "
        f"session={state.has_session}",
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("info.txt", "\n".join(info) + "\n")
        zf.writestr(
            "env_redacted.txt",
            "\n".join(f"{k}={v}" for k, v in redact.redact_env(env).items()) + "\n",
        )
        for name in ("telegram-mcp.log", "helpers.log"):
            p = settings.log_dir / name
            if p.is_file():
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-3000:]
                zf.writestr(name, redact.redact_text("\n".join(lines)) + "\n")
    Path(path).write_bytes(buf.getvalue())
    QMessageBox.information(
        parent,
        "诊断包",
        f"已保存到：\n{path}\n\n已去掉 api_hash、session、手机号、聊天 ID 和用户名。"
        "发到 GitHub 之前仍建议自己打开看一眼。",
    )


def launch_command() -> tuple[str, str]:
    """(target, arguments) that start this manager, for shortcuts."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return str(pythonw if pythonw.exists() else exe), "-m tgmcp_desk"


SHORTCUT_FOLDERS = {"desktop": "Desktop", "programs": "Programs", "startup": "Startup"}


def create_shortcut(kind: str, name: str = "TGMCP Desk") -> bool:
    """Create a Windows .lnk on the Desktop, in the Start Menu or in Startup."""
    if sys.platform != "win32":
        return False
    target, args = launch_command()
    ps = (
        "$d=[Environment]::GetFolderPath($env:TGMCP_FOLDER);"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d ($env:TGMCP_NAME+'.lnk')));"
        "$s.TargetPath=$env:TGMCP_TARGET;$s.Arguments=$env:TGMCP_ARGS;"
        "$s.WorkingDirectory=$env:TGMCP_WD;$s.IconLocation=$env:TGMCP_TARGET;$s.Save()"
    )
    env = {
        **os.environ,
        "TGMCP_FOLDER": SHORTCUT_FOLDERS[kind],
        "TGMCP_NAME": name,
        "TGMCP_TARGET": target,
        "TGMCP_ARGS": args,
        "TGMCP_WD": str(Path(target).parent),
    }
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
        env=env,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    return proc.returncode == 0


def remove_shortcut(kind: str, name: str = "TGMCP Desk") -> None:
    if sys.platform != "win32":
        return
    ps = "Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath($env:TGMCP_FOLDER)) ($env:TGMCP_NAME+'.lnk')) -ErrorAction SilentlyContinue"
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
        env={**os.environ, "TGMCP_FOLDER": SHORTCUT_FOLDERS[kind], "TGMCP_NAME": name},
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
