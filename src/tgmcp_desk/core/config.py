"""What the manager writes into telegram-mcp's ``.env``, and client config snippets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

DEVICE_MODEL = "TGMCP Desk"
SESSION_NAME = "telegram_session"

_API_ID_RE = re.compile(r"^\d{3,12}$")
_API_HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def check_api_credentials(api_id: str, api_hash: str) -> list[str]:
    out = []
    if not _API_ID_RE.match(api_id.strip()):
        out.append("api_id 应该是一串数字")
    if not _API_HASH_RE.match(api_hash.strip()):
        out.append("api_hash 应该是 32 位的十六进制字符（0-9、a-f）")
    return out


def credential_env(api_id: str, api_hash: str) -> dict[str, str | None]:
    return {
        "TELEGRAM_API_ID": api_id.strip(),
        "TELEGRAM_API_HASH": api_hash.strip(),
    }


def base_env(port: int, existing: dict[str, str] | None = None) -> dict[str, str | None]:
    """Settings the manager relies on: local HTTP transport on 127.0.0.1 and a file session.

    An existing ``TELEGRAM_SESSION_NAME`` is kept so adopting an old install
    does not lose its login.
    """
    existing = existing or {}
    return {
        "TELEGRAM_SESSION_NAME": existing.get("TELEGRAM_SESSION_NAME") or SESSION_NAME,
        "MCP_TRANSPORT": "http",
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(port),
    }


def device_env(existing: dict[str, str]) -> dict[str, str | None]:
    """Name this login in Telegram's Settings > Devices, unless the user chose one."""
    if existing.get("TELEGRAM_DEVICE_MODEL"):
        return {}
    return {"TELEGRAM_DEVICE_MODEL": DEVICE_MODEL}


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"


def endpoint_from_env(env: dict[str, str]) -> Endpoint:
    host = env.get("MCP_HOST") or "127.0.0.1"
    try:
        port = int(env.get("MCP_PORT") or 8765)
    except ValueError:
        port = 8765
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    return Endpoint(host, port)


def client_snippets(ep: Endpoint, name: str = "telegram") -> dict[str, str]:
    """Copy-paste config for common MCP clients, keyed by a display label."""
    url = ep.url
    return {
        "Claude Code（命令行）": f"claude mcp add --transport http {name} {url}",
        "Cursor / Windsurf（mcp.json）": json.dumps(
            {"mcpServers": {name: {"url": url}}}, indent=2, ensure_ascii=False
        ),
        "VS Code（.vscode/mcp.json）": json.dumps(
            {"servers": {name: {"type": "http", "url": url}}}, indent=2, ensure_ascii=False
        ),
        "Claude Desktop（经 mcp-remote，需要 Node.js）": json.dumps(
            {"mcpServers": {name: {"command": "npx", "args": ["-y", "mcp-remote", url]}}},
            indent=2,
            ensure_ascii=False,
        ),
    }
