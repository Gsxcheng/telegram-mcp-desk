"""QProcess wrappers: the telegram-mcp server and the JSON-lines helper scripts."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QIODevice, QObject, QProcess, QProcessEnvironment, QTimer, Signal

from ..core import installer, ports, supervisor
from ..core.config import endpoint_from_env
from ..core.envfile import EnvFile
from ..core.settings import Settings
from .common import helper_script


def _qenv(env: dict[str, str]) -> QProcessEnvironment:
    q = QProcessEnvironment()
    for k, v in env.items():
        q.insert(k, v)
    return q


def append_log(path: Path, line: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [管理器] {line}\n")
    except OSError:
        pass


class HelperProcess(QObject):
    """Runs one helper script inside telegram-mcp's venv and relays its JSON events."""

    event = Signal(dict)
    finished = Signal(int)

    def __init__(self, settings: Settings, script: str, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.script = script
        self.proc = QProcess(self)
        self._buf = b""
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)

    def start(self) -> None:
        python = self.settings.venv_python()
        if not python.is_file():
            self.event.emit(
                {
                    "event": "error",
                    "kind": "not_installed",
                    "message": "telegram-mcp 还没装好（找不到 .venv），请先完成安装。",
                }
            )
            self.finished.emit(1)
            return
        log_dir = self.settings.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        self.proc.setStandardErrorFile(str(log_dir / "helpers.log"), QIODevice.OpenModeFlag.Append)
        self.proc.setWorkingDirectory(str(self.settings.install_path))
        self.proc.setProcessEnvironment(_qenv(installer.child_env()))
        self.proc.start(str(python), [str(helper_script(self.script))])

    def send(self, message: dict) -> None:
        if self.proc.state() == QProcess.ProcessState.Running:
            self.proc.write((json.dumps(message) + "\n").encode())

    def cancel(self) -> None:
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.closeWriteChannel()
            if not self.proc.waitForFinished(1500):
                self.proc.kill()
                self.proc.waitForFinished(1500)

    def _read(self) -> None:
        self._buf += bytes(self.proc.readAllStandardOutput())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict):
                self.event.emit(msg)

    def _finished(self, code: int, _status) -> None:
        self._read()
        self.finished.emit(code)

    def _error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self.event.emit(
                {
                    "event": "error",
                    "kind": "start",
                    "message": "无法启动 Python：" + self.proc.errorString(),
                }
            )
            self.finished.emit(1)


class ServerController(QObject):
    """Owns the telegram-mcp process: start/stop, health checks, auto-restart.

    States: ``stopped``, ``starting``, ``running``, ``waiting`` (restart
    scheduled), ``external`` (port answered by a process we did not start).
    """

    stateChanged = Signal(str, str)
    notify = Signal(str, str)  # (message, level: info|warning|error)

    def __init__(self, settings: Settings, parent: QObject | None = None):
        super().__init__(parent)
        self.settings = settings
        self.tracker = supervisor.RestartTracker()
        self.proc: QProcess | None = None
        self.want_running = False
        self.state = "stopped"
        self.state_text = "已停止"
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._restart_due)
        self._poll = QTimer(self)
        self._poll.setInterval(2000)
        self._poll.timeout.connect(self.refresh)
        self._poll.start()

    # -- info ----------------------------------------------------------------

    def env(self) -> dict[str, str]:
        return EnvFile.load(self.settings.env_path).as_dict()

    def port(self) -> int:
        return endpoint_from_env(self.env()).port

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    # -- control -------------------------------------------------------------

    def start(self) -> None:
        self._restart_timer.stop()
        if self.is_alive():
            return
        python = self.settings.venv_python()
        if not python.is_file():
            self.notify.emit("telegram-mcp 还没装好，请先运行设置向导。", "error")
            return
        port = self.port()
        if ports.is_listening(port):
            self.want_running = False
            self.notify.emit(f"端口 {port} 已被占用：可能已有一份 telegram-mcp 在运行。", "warning")
            self.refresh()
            return
        log = self.settings.log_path
        log.parent.mkdir(parents=True, exist_ok=True)
        supervisor.rotate_log(log)
        append_log(log, "启动")
        proc = QProcess(self)
        proc.setWorkingDirectory(str(self.settings.install_path))
        proc.setProcessEnvironment(_qenv(installer.child_env()))
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.setStandardOutputFile(str(log), QIODevice.OpenModeFlag.Append)
        proc.finished.connect(lambda code, _s, p=proc: self._on_finished(p, code))
        proc.errorOccurred.connect(lambda err, p=proc: self._on_error(p, err))
        self.proc = proc
        self.want_running = True
        self.tracker.on_started(time.monotonic())
        proc.start(str(python), ["main.py"])
        self.refresh()

    def stop(self) -> None:
        self.want_running = False
        self._restart_timer.stop()
        proc, self.proc = self.proc, None
        if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
            proc.kill()
            proc.waitForFinished(5000)
            append_log(self.settings.log_path, "停止")
        self.refresh()

    def stop_external(self) -> list[int]:
        """Kill whatever listens on our port (Windows). Returns the PIDs killed."""
        import os
        import signal

        killed = []
        for pid in ports.listening_pids(self.port()):
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(pid)
            except OSError:
                pass
        if killed:
            append_log(self.settings.log_path, f"结束了外部进程 {killed}")
        self.refresh()
        return killed

    def restart(self) -> None:
        self.stop()
        self.tracker.reset()
        self.want_running = True
        self._restart_timer.start(1500)
        self.refresh()

    def wait_port_free(self, timeout_ms: int = 10000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        port = self.port()
        while time.monotonic() < deadline:
            if not ports.is_listening(port):
                return True
            time.sleep(0.2)
        return False

    # -- internals -----------------------------------------------------------

    def _restart_due(self) -> None:
        if self.want_running:
            self.start()

    def _on_error(self, proc: QProcess, err) -> None:
        if err == QProcess.ProcessError.FailedToStart and proc is self.proc:
            self.proc = None
            self.want_running = False
            self.notify.emit("启动失败：" + proc.errorString(), "error")
            self.refresh()

    def _on_finished(self, proc: QProcess, code: int) -> None:
        if proc is not self.proc:
            return  # stopped on purpose
        self.proc = None
        decision = self.tracker.on_exit(time.monotonic(), self.settings.auto_restart)
        append_log(
            self.settings.log_path, f"进程退出（代码 {code}，运行 {int(decision.ran_seconds)} 秒）"
        )
        if not self.want_running:
            self.refresh()
            return
        if decision.restart_in is not None:
            self._restart_timer.start(int(decision.restart_in * 1000))
            self.notify.emit(
                f"telegram-mcp 意外退出，{int(decision.restart_in)} 秒后自动重启。", "warning"
            )
        else:
            self.want_running = False
            if decision.gave_up:
                self.notify.emit(
                    f"连续 {decision.fast_fails} 次刚启动就退出，已停止自动重启。请看日志找原因。",
                    "error",
                )
            else:
                self.notify.emit("telegram-mcp 已退出。", "warning")
        self.refresh()

    def _set(self, state: str, text: str) -> None:
        if (state, text) != (self.state, self.state_text):
            self.state, self.state_text = state, text
            self.stateChanged.emit(state, text)

    def refresh(self) -> None:
        port = self.port()
        listening = ports.is_listening(port)
        alive = self.is_alive()
        if alive and listening:
            self.tracker.on_healthy(time.monotonic())
            self._set("running", f"运行中（端口 {port}）")
        elif alive:
            self._set("starting", "启动中…")
        elif self._restart_timer.isActive():
            self._set("starting", "等待重启…")
        elif listening:
            self._set("external", f"运行中（不是本程序启动的，端口 {port}）")
        else:
            self._set("stopped", "已停止")
