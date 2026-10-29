"""Log in to Telegram (phone number + code + optional 2FA password) and save a session file.

Run by the manager inside telegram-mcp's environment; see ``_common`` for the
line protocol. The phone number, code and password are only held in memory
for the duration of the login and are never printed or written to disk.
The resulting ``<TELEGRAM_SESSION_NAME>.session`` file is what telegram-mcp
uses afterwards.
"""

from __future__ import annotations

import asyncio
import sys

from _common import describe_me, emit, fail, load_env, make_client, read_message

CONNECT_TIMEOUT = 45


def _code_channel(sent) -> str:
    name = type(getattr(sent, "type", None)).__name__
    if name == "SentCodeTypeApp":
        return "app"
    if name in ("SentCodeTypeSms", "SentCodeTypeFragmentSms", "SentCodeTypeFirebaseSms"):
        return "sms"
    if name == "SentCodeTypeCall":
        return "call"
    return "other"


async def _ask(field: str, **extra) -> str | None:
    emit("need", field=field, **extra)
    msg = await read_message()
    if msg.get("cancel"):
        return None
    return str(msg.get(field, "")).strip()


async def login() -> None:
    from telethon import errors

    load_env()
    client = make_client(use_string_session=False)
    emit("connecting")
    try:
        await asyncio.wait_for(client.connect(), CONNECT_TIMEOUT)
    except (TimeoutError, OSError) as exc:
        fail(
            "network", f"连不上 Telegram：{type(exc).__name__}。请检查代理设置和代理软件是否开着。"
        )
    try:
        if await client.is_user_authorized():
            emit("done", already=True, me=describe_me(await client.get_me()))
            return

        while True:
            phone = await _ask("phone")
            if phone is None:
                emit("cancelled")
                return
            try:
                sent = await client.send_code_request(phone)
                break
            except errors.PhoneNumberInvalidError:
                emit("retry", field="phone", message="手机号不对。要带国家代码，例如 +86 开头。")
            except errors.PhoneNumberBannedError:
                fail("banned", "这个手机号被 Telegram 封禁了。")
            except errors.FloodWaitError as exc:
                fail("flood", f"请求太频繁，Telegram 要求等 {exc.seconds} 秒后再试。")

        channel = _code_channel(sent)
        while True:
            code = await _ask("code", via=channel)
            if code is None:
                emit("cancelled")
                return
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                break
            except errors.PhoneCodeInvalidError:
                emit("retry", field="code", message="验证码不对，请重新输入。")
            except errors.PhoneCodeExpiredError:
                fail("expired", "验证码过期了，请重新开始登录。")
            except errors.SessionPasswordNeededError:
                await _password_step(client)
                break
            except errors.FloodWaitError as exc:
                fail("flood", f"尝试太频繁，Telegram 要求等 {exc.seconds} 秒后再试。")

        emit("done", already=False, me=describe_me(await client.get_me()))
    finally:
        await client.disconnect()


async def _password_step(client) -> None:
    from telethon import errors

    hint = ""
    try:
        from telethon.tl.functions.account import GetPasswordRequest

        hint = (await client(GetPasswordRequest())).hint or ""
    except Exception:
        pass
    while True:
        password = await _ask("password", hint=hint)
        if password is None:
            emit("cancelled")
            sys.exit(0)
        try:
            await client.sign_in(password=password)
            return
        except errors.PasswordHashInvalidError:
            emit("retry", field="password", message="二步验证密码不对，请重新输入。")
        except errors.FloodWaitError as exc:
            fail("flood", f"尝试太频繁，Telegram 要求等 {exc.seconds} 秒后再试。")


def main() -> None:
    try:
        asyncio.run(login())
    except SystemExit:
        raise
    except Exception as exc:  # report, never print secrets
        fail("unexpected", f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
