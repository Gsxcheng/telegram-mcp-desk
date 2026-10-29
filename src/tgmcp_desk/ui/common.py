"""Small UI utilities: icons, background work, helper script paths."""

from __future__ import annotations

import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPainterPath, QPixmap

# Deliberately not Telegram's blue: the Telegram API terms forbid using its logo.
BRAND = QColor(79, 70, 229)
STATE_COLORS = {
    "running": QColor(46, 160, 67),
    "starting": QColor(230, 140, 20),
    "stopped": QColor(128, 128, 128),
    "error": QColor(200, 50, 50),
}


def package_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "tgmcp_desk"
    return Path(__file__).resolve().parent.parent


def helper_script(name: str) -> Path:
    return package_dir() / "helpers" / name


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = size * 0.22
        path.addRoundedRect(QRectF(0, 0, size, size), r, r)
        p.fillPath(path, BRAND)
        font = QFont("Segoe UI", 1, QFont.Weight.Bold)
        font.setPixelSize(max(6, int(size * 0.42)))
        p.setFont(font)
        p.setPen(Qt.GlobalColor.white)
        p.drawText(
            QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "MCP" if size >= 48 else "M"
        )
        p.end()
        icon.addPixmap(pix)
    return icon


def state_icon(state: str) -> QIcon:
    color = STATE_COLORS.get(state, STATE_COLORS["stopped"])
    icon = QIcon()
    for size in (16, 20, 24, 32):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
        font = QFont("Segoe UI", 1, QFont.Weight.Bold)
        font.setPixelSize(int(size * 0.62))
        p.setFont(font)
        p.setPen(Qt.GlobalColor.white)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "M")
        p.end()
        icon.addPixmap(pix)
    return icon


def open_path(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class _Bridge(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


_running: set[_Bridge] = set()


def run_in_thread(
    fn: Callable[..., Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_progress: Callable[[Any], None] | None = None,
) -> None:
    """Run ``fn(progress)`` in a daemon thread; callbacks run on the UI thread.

    ``fn`` receives a ``progress(value)`` callable it may call from the worker.
    Exceptions are reported to ``on_error`` as text.
    """
    bridge = _Bridge()
    _running.add(bridge)
    if on_done:
        bridge.done.connect(on_done)
    if on_error:
        bridge.failed.connect(on_error)
    if on_progress:
        bridge.progress.connect(on_progress)
    bridge.done.connect(lambda _=None: _running.discard(bridge))
    bridge.failed.connect(lambda _=None: _running.discard(bridge))

    def work():
        try:
            result = fn(bridge.progress.emit)
        except Exception as exc:  # surfaced in the UI
            msg = str(exc) or type(exc).__name__
            if not isinstance(exc, (OSError, ValueError, RuntimeError)) and not str(exc):
                msg = traceback.format_exc(limit=3)
            bridge.failed.emit(msg)
        else:
            bridge.done.emit(result)

    threading.Thread(target=work, daemon=True).start()
