"""Manager settings and well-known paths.

Settings live in the per-user data directory (``%LOCALAPPDATA%\\TGMCP Desk`` on
Windows). They only hold manager preferences and paths -- never Telegram
credentials, which stay in telegram-mcp's own ``.env``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "TGMCP Desk"
UPSTREAM_REPO = "chigwell/telegram-mcp"
# Upstream release this manager was tested against; the wizard offers it by default.
DEFAULT_UPSTREAM_TAG = "v3.2.98"


def data_dir() -> Path:
    override = os.environ.get("TGMCP_DESK_HOME")
    if override:
        return Path(override)
    return Path(user_data_dir(APP_NAME, appauthor=False, roaming=False))


def settings_path() -> Path:
    return data_dir() / "settings.json"


@dataclass
class Settings:
    install_dir: str = ""
    upstream_tag: str = DEFAULT_UPSTREAM_TAG
    uv_path: str = ""
    setup_done: bool = False
    auto_restart: bool = True
    start_server_on_launch: bool = True
    # Proxy for downloads (uv, Python, upstream source); empty = system default.
    download_proxy: str = ""

    @property
    def install_path(self) -> Path:
        return Path(self.install_dir) if self.install_dir else default_install_dir()

    @property
    def env_path(self) -> Path:
        return self.install_path / ".env"

    @property
    def log_dir(self) -> Path:
        return self.install_path / "logs"

    @property
    def log_path(self) -> Path:
        return self.log_dir / "telegram-mcp.log"

    def venv_python(self) -> Path:
        venv = self.install_path / ".venv"
        if sys.platform == "win32":
            return venv / "Scripts" / "python.exe"
        return venv / "bin" / "python"

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or settings_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        path = path or settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def default_install_dir() -> Path:
    return data_dir() / "telegram-mcp"
