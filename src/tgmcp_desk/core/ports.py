"""Pick a local port telegram-mcp can actually listen on.

On Windows, Hyper-V / WSL / Docker reserve blocks of TCP ports (visible with
``netsh interface ipv4 show excludedportrange protocol=tcp``). Binding inside
such a block fails with "access denied" even though nothing is listening --
which is what happened with telegram-mcp's default 8765.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from collections.abc import Callable, Iterable

DEFAULT_PORT = 18765
_RANGE_RE = re.compile(r"^\s*(\d+)\s+(\d+)\b")


def parse_excluded_ranges(netsh_output: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for line in netsh_output.splitlines():
        m = _RANGE_RE.match(line)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if 0 < start <= end <= 65535:
                ranges.append((start, end))
    return ranges


def excluded_ranges() -> list[tuple[int, int]]:
    """Reserved TCP ranges on this machine (empty outside Windows or on error)."""
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_excluded_ranges(out)


def in_ranges(port: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(start <= port <= end for start, end in ranges)


def can_bind(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def is_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pick_port(
    preferred: int = DEFAULT_PORT,
    ranges: Iterable[tuple[int, int]] | None = None,
    bindable: Callable[[int], bool] = can_bind,
    attempts: int = 200,
) -> int:
    """First port from ``preferred`` upward that is not reserved and can be bound."""
    ranges = list(excluded_ranges() if ranges is None else ranges)
    port = preferred
    for _ in range(attempts):
        if 1024 <= port <= 65535 and not in_ranges(port, ranges) and bindable(port):
            return port
        port += 1
    raise RuntimeError(f"从 {preferred} 往后 {attempts} 个端口都不能用")


def parse_netstat_listeners(netstat_output: str, port: int) -> list[int]:
    """PIDs listening on ``port`` in ``netstat -ano -p tcp`` output (Windows)."""
    pids: list[int] = []
    for line in netstat_output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        local = parts[1]
        if local.rsplit(":", 1)[-1] == str(port):
            try:
                pid = int(parts[4])
            except ValueError:
                continue
            if pid and pid not in pids:
                pids.append(pid)
    return pids


def listening_pids(port: int) -> list[int]:
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_netstat_listeners(out, port)
