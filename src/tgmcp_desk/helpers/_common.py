"""Shared code for helper scripts.

Helpers run inside telegram-mcp's own virtual environment (its Python, its
Telethon), with the telegram-mcp install directory as the working directory.
They talk to the manager over stdin/stdout, one JSON object per line:

* helper -> manager: ``{"event": "...", ...}``
* manager -> helper: ``{"phone": "..."}``, ``{"code": "..."}``, ``{"cancel": true}``...

Nothing secret is printed: no api_hash, session data, code or password.
Diagnostics go to stderr, which the manager writes to a log file.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

HERE = os.getcwd()


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=True) + "\n")
    sys.stdout.flush()


async def read_message() -> dict:
    """Next JSON line from the manager; ``{"cancel": True}`` on EOF."""
    loop = asyncio.get_running_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    if not line:
        return {"cancel": True}
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        return {}
    return msg if isinstance(msg, dict) else {}


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - telegram-mcp depends on python-dotenv
        return
    load_dotenv(os.path.join(HERE, ".env"), override=True)


def _truthy(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_proxy():
    """``(proxy, connection)`` kwargs, following telegram-mcp's TELEGRAM_PROXY_* rules."""
    proxy_type = (os.getenv("TELEGRAM_PROXY_TYPE") or "").strip().lower()
    if not proxy_type:
        return None, None
    host = os.getenv("TELEGRAM_PROXY_HOST")
    port = os.getenv("TELEGRAM_PROXY_PORT")
    if not host or not port:
        raise RuntimeError("代理设置不完整：缺少 TELEGRAM_PROXY_HOST 或 TELEGRAM_PROXY_PORT")
    if proxy_type == "mtproxy":
        from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

        secret = os.getenv("TELEGRAM_PROXY_SECRET") or ""
        return (host, int(port), secret), ConnectionTcpMTProxyRandomizedIntermediate
    if proxy_type not in {"socks5", "socks4", "http"}:
        raise RuntimeError(f"不支持的代理类型：{proxy_type}")
    proxy = {
        "proxy_type": proxy_type,
        "addr": host,
        "port": int(port),
        "rdns": _truthy(os.getenv("TELEGRAM_PROXY_RDNS"), True),
    }
    if os.getenv("TELEGRAM_PROXY_USERNAME"):
        proxy["username"] = os.environ["TELEGRAM_PROXY_USERNAME"]
    if os.getenv("TELEGRAM_PROXY_PASSWORD"):
        proxy["password"] = os.environ["TELEGRAM_PROXY_PASSWORD"]
    return proxy, None


def session_path() -> str:
    name = os.getenv("TELEGRAM_SESSION_NAME") or "telegram_session"
    return name if os.path.isabs(name) else os.path.join(HERE, name)


def make_client(use_string_session: bool = True):
    """A TelegramClient configured exactly like telegram-mcp's default account."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("还没有填写 api_id / api_hash")

    session_string = (os.getenv("TELEGRAM_SESSION_STRING") or "").strip()
    session = (
        StringSession(session_string) if (use_string_session and session_string) else session_path()
    )

    kwargs = {}
    proxy, connection = build_proxy()
    if proxy is not None:
        kwargs["proxy"] = proxy
    if connection is not None:
        kwargs["connection"] = connection
    try:
        from telegram_mcp.client_identity import client_identity_kwargs

        kwargs.update(client_identity_kwargs())
    except Exception:  # older telegram-mcp versions
        pass
    return TelegramClient(session, int(api_id), api_hash, **kwargs)


def describe_me(me) -> dict:
    """Minimal, display-only description of the logged-in account."""
    name = " ".join(p for p in (getattr(me, "first_name", ""), getattr(me, "last_name", "")) if p)
    return {"name": name or "（无名字）", "username": getattr(me, "username", "") or ""}


def fail(kind: str, message: str, code: int = 1) -> None:
    emit("error", kind=kind, message=message)
    sys.exit(code)
