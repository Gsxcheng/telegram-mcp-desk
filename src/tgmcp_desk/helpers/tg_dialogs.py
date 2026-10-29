"""List the account's chats (read-only) for the allowlist picker.

Only calls ``iter_dialogs``: sends nothing, marks nothing as read. Emits one
``{"event": "dialogs", "dialogs": [...]}`` line. telegram-mcp must be stopped
first: one session cannot be used by two processes at once.
"""

from __future__ import annotations

import asyncio

from _common import emit, fail, load_env, make_client

TIMEOUT = 90


def kind_of(entity) -> str:
    from telethon.tl.types import Channel, Chat, User

    if isinstance(entity, Channel):
        return "channel" if entity.broadcast else "group"
    if isinstance(entity, Chat):
        return "group"
    if isinstance(entity, User):
        return "bot" if entity.bot else "user"
    return "other"


async def list_dialogs() -> list[dict]:
    load_env()
    client = make_client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            fail("not_logged_in", "还没有登录 Telegram，请先在向导里登录。")
        items = []
        async for d in client.iter_dialogs():
            entity = d.entity
            items.append(
                {
                    "id": str(d.id),
                    "name": d.name or "",
                    "type": kind_of(entity),
                    "username": getattr(entity, "username", None) or "",
                    "archived": bool(getattr(d, "archived", False)),
                }
            )
        return items
    finally:
        await client.disconnect()


def main() -> None:
    try:
        dialogs = asyncio.run(asyncio.wait_for(list_dialogs(), TIMEOUT))
    except SystemExit:
        raise
    except TimeoutError:
        fail("timeout", "读取对话列表超时，请检查代理。")
    except Exception as exc:
        fail("unexpected", f"{type(exc).__name__}: {exc}")
    emit("dialogs", dialogs=dialogs)


if __name__ == "__main__":
    main()
