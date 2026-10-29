"""Install telegram-mcp: get uv, download a pinned upstream release, sync its environment.

Upstream source comes straight from GitHub (``chigwell/telegram-mcp`` release
archives). Never from PyPI: the PyPI name ``telegram-mcp`` belongs to an
unrelated project.

The functions here are synchronous; the UI runs them in a worker thread.
"""

from __future__ import annotations

import fnmatch
import io
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .settings import UPSTREAM_REPO, data_dir

UV_VERSION = "0.11.32"
MARKER = ".tgmcp-desk.json"
# Files in an install directory that belong to the user, never replaced on upgrade.
USER_FILES = (".env", ".env.bak", "*.session", "*.session-journal", "logs", ".venv", MARKER)

Progress = Callable[[int, int], None]  # (bytes_done, bytes_total or 0)


class InstallError(Exception):
    pass


# -- uv ----------------------------------------------------------------------


def _uv_exe_name() -> str:
    return "uv.exe" if sys.platform == "win32" else "uv"


def find_uv(configured: str = "") -> Path | None:
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    which = shutil.which("uv")
    if which:
        candidates.append(Path(which))
    home = Path.home()
    exe = _uv_exe_name()
    candidates += [
        data_dir() / "bin" / exe,
        home / ".local" / "bin" / exe,
        home / ".cargo" / "bin" / exe,
    ]
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        candidates.append(Path(local_app) / "Microsoft" / "WinGet" / "Links" / exe)
    for c in candidates:
        if c.is_file():
            return c
    return None


def uv_asset_name(system: str | None = None, machine: str | None = None) -> str:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if system == "windows":
        return f"uv-{arch}-pc-windows-msvc.zip"
    if system == "darwin":
        return f"uv-{arch}-apple-darwin.tar.gz"
    return f"uv-{arch}-unknown-linux-gnu.tar.gz"


def uv_download_url(version: str = UV_VERSION) -> str:
    return f"https://github.com/astral-sh/uv/releases/download/{version}/{uv_asset_name()}"


def install_uv(proxy: str = "", progress: Progress | None = None) -> Path:
    """Download uv into the manager's data dir (Windows zip only)."""
    if sys.platform != "win32":
        raise InstallError("自动下载 uv 只支持 Windows；请按 https://docs.astral.sh/uv/ 安装")
    dest_dir = data_dir() / "bin"
    dest_dir.mkdir(parents=True, exist_ok=True)
    data = download(uv_download_url(), proxy=proxy, progress=progress)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            base = member.rsplit("/", 1)[-1]
            if base in ("uv.exe", "uvx.exe"):
                (dest_dir / base).write_bytes(zf.read(member))
    exe = dest_dir / "uv.exe"
    if not exe.is_file():
        raise InstallError("下载的 uv 压缩包里没有 uv.exe")
    return exe


# -- downloads ---------------------------------------------------------------


def download(
    url: str, proxy: str = "", progress: Progress | None = None, timeout: float = 60
) -> bytes:
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "tgmcp-desk"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            buf = io.BytesIO()
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                buf.write(chunk)
                if progress:
                    progress(buf.tell(), total)
            return buf.getvalue()
    except OSError as exc:
        hint = "" if proxy else "（国内网络可在设置里填下载代理，例如 http://127.0.0.1:7890）"
        raise InstallError(f"下载失败：{url}\n{exc}{hint}") from exc


def source_archive_url(tag: str) -> str:
    return f"https://github.com/{UPSTREAM_REPO}/archive/refs/tags/{tag}.zip"


# -- install directory -------------------------------------------------------


@dataclass(frozen=True)
class InstallState:
    exists: bool
    empty: bool
    managed: bool  # has our marker
    is_upstream: bool  # looks like a telegram-mcp checkout
    tag: str = ""
    has_env: bool = False
    has_venv: bool = False
    has_session: bool = False


def inspect_dir(path: Path) -> InstallState:
    path = Path(path)
    if not path.exists():
        return InstallState(False, True, False, False)
    entries = list(path.iterdir())
    marker = path / MARKER
    tag = ""
    if marker.is_file():
        try:
            tag = json.loads(marker.read_text(encoding="utf-8")).get("tag", "")
        except (OSError, json.JSONDecodeError):
            pass
    pyproject = path / "pyproject.toml"
    is_upstream = False
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
            is_upstream = 'name = "telegram-mcp"' in text and (path / "telegram_mcp").is_dir()
        except OSError:
            pass
    return InstallState(
        exists=True,
        empty=not entries,
        managed=marker.is_file(),
        is_upstream=is_upstream,
        tag=tag,
        has_env=(path / ".env").is_file(),
        has_venv=(path / ".venv").is_dir(),
        has_session=any(path.glob("*.session")),
    )


def _is_user_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in USER_FILES)


def install_source(archive: bytes, target: Path, tag: str) -> None:
    """Unpack an upstream release archive into ``target``.

    ``target`` must be empty, missing, or an install this manager created
    (marker present) or an upstream checkout; anything else is refused so a
    wrong folder choice can never wipe unrelated files. User files
    (``.env``, sessions, logs, ``.venv``) are kept.
    """
    target = Path(target)
    state = inspect_dir(target)
    if state.exists and not state.empty and not (state.managed or state.is_upstream):
        raise InstallError(f"{target} 不是空文件夹，也不像 telegram-mcp 的安装目录；请换一个文件夹")
    with tempfile.TemporaryDirectory(prefix="tgmcp-src-") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for member in zf.infolist():
                parts = Path(member.filename).parts
                if any(p == ".." for p in parts) or Path(member.filename).is_absolute():
                    raise InstallError("压缩包里有可疑路径，已停止")
            zf.extractall(tmp_path)
        roots = [p for p in tmp_path.iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "pyproject.toml").is_file():
            raise InstallError("下载的压缩包结构不对（找不到 pyproject.toml）")
        src = roots[0]
        if not (src / "telegram_mcp").is_dir():
            raise InstallError("下载的压缩包不是 telegram-mcp")
        target.mkdir(parents=True, exist_ok=True)
        for entry in list(target.iterdir()):
            if _is_user_file(entry.name):
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        for entry in src.iterdir():
            if _is_user_file(entry.name):
                continue
            shutil.move(str(entry), str(target / entry.name))
    write_marker(target, tag)


def write_marker(target: Path, tag: str) -> None:
    (Path(target) / MARKER).write_text(
        json.dumps({"tag": tag, "installed_at": int(time.time()), "by": "tgmcp-desk"}),
        encoding="utf-8",
    )


def uv_sync_command(uv: Path) -> list[str]:
    return [str(uv), "sync", "--extra", "proxy"]


def child_env(proxy: str = "") -> dict[str, str]:
    """Environment for uv / telegram-mcp child processes."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if proxy:
        env["HTTPS_PROXY"] = proxy
        env["HTTP_PROXY"] = proxy
    return env
