"""Restart policy and log rotation for the telegram-mcp process.

Kept free of Qt and of real processes so it can be unit tested; the UI's
``ServerController`` feeds it start/exit events and follows its decisions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RestartPolicy:
    delay_seconds: float = 30.0
    # A run shorter than this counts as "died right after starting".
    fast_fail_seconds: float = 60.0
    max_fast_fails: int = 5


@dataclass(frozen=True)
class ExitDecision:
    restart_in: float | None  # seconds until restart, or None to stay stopped
    fast_fails: int
    gave_up: bool
    ran_seconds: float


class RestartTracker:
    def __init__(self, policy: RestartPolicy | None = None):
        self.policy = policy or RestartPolicy()
        self.fast_fails = 0
        self.started_at: float | None = None

    def on_started(self, now: float) -> None:
        self.started_at = now

    def on_healthy(self, now: float) -> None:
        """Called while the server answers; a long healthy run clears the fail streak."""
        if self.started_at is not None and now - self.started_at >= self.policy.fast_fail_seconds:
            self.fast_fails = 0

    def reset(self) -> None:
        self.fast_fails = 0

    def on_exit(self, now: float, auto_restart: bool) -> ExitDecision:
        ran = 0.0 if self.started_at is None else max(0.0, now - self.started_at)
        self.started_at = None
        if ran < self.policy.fast_fail_seconds:
            self.fast_fails += 1
        else:
            self.fast_fails = 0
        if not auto_restart:
            return ExitDecision(None, self.fast_fails, False, ran)
        if self.fast_fails >= self.policy.max_fast_fails:
            return ExitDecision(None, self.fast_fails, True, ran)
        return ExitDecision(self.policy.delay_seconds, self.fast_fails, False, ran)


def rotate_log(path: Path, max_bytes: int = 20 * 1024 * 1024) -> bool:
    """Rename ``path`` to ``path.old`` when it is larger than ``max_bytes``."""
    path = Path(path)
    try:
        if path.stat().st_size <= max_bytes:
            return False
    except FileNotFoundError:
        return False
    old = path.with_name(path.name + ".old")
    try:
        os.replace(path, old)
    except OSError:
        return False
    return True


def read_tail(path: Path, offset: int, max_bytes: int = 256 * 1024) -> tuple[str, int]:
    """Text appended to ``path`` since ``offset``; returns ``(text, new_offset)``.

    If the file shrank (rotated) reading restarts from the beginning. At most
    ``max_bytes`` are returned per call, taken from the end.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return "", 0
    if size < offset:
        offset = 0
    if size == offset:
        return "", offset
    start = max(offset, size - max_bytes)
    with path.open("rb") as f:
        f.seek(start)
        data = f.read(size - start)
    return data.decode("utf-8", "replace"), size
