"""Fake Telethon client. Scenario via env:

FAKE_TG_AUTHORIZED=1  session already logged in
FAKE_TG_2FA=1         account has a 2FA password ("pw")
FAKE_TG_OFFLINE=1     connect() fails
Valid phone: +10000000000, valid code: 11111.
The constructor records its arguments to $FAKE_TG_RECORD (JSON) when set.
"""

import json
import os

from . import errors
from .tl.functions.account import GetPasswordRequest
from .tl.types import Channel, Chat, SentCodeTypeApp, User


class _Sent:
    phone_code_hash = "hash"
    type = SentCodeTypeApp()


class _Dialog:
    def __init__(self, id, name, entity, archived=False):
        self.id, self.name, self.entity, self.archived = id, name, entity, archived


class _Pwd:
    hint = "fake hint"


class TelegramClient:
    def __init__(self, session, api_id, api_hash, **kwargs):
        record = os.environ.get("FAKE_TG_RECORD")
        if record:
            with open(record, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "session": session if isinstance(session, str) else "string",
                        "api_id": api_id,
                        "kwargs": {k: str(v) for k, v in kwargs.items()},
                    },
                    f,
                )
        self.authorized = os.environ.get("FAKE_TG_AUTHORIZED") == "1"
        self.need_2fa = os.environ.get("FAKE_TG_2FA") == "1"

    async def connect(self):
        if os.environ.get("FAKE_TG_OFFLINE") == "1":
            raise OSError("offline")

    async def disconnect(self):
        pass

    async def is_user_authorized(self):
        return self.authorized

    async def send_code_request(self, phone):
        if phone != "+10000000000":
            raise errors.PhoneNumberInvalidError()
        return _Sent()

    async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
        if password is not None:
            if password != "pw":
                raise errors.PasswordHashInvalidError()
            self.authorized = True
            return
        if code != "11111":
            raise errors.PhoneCodeInvalidError()
        if self.need_2fa:
            raise errors.SessionPasswordNeededError()
        self.authorized = True

    async def get_me(self):
        return User(first_name="Test", last_name="User", username="test_user")

    async def __call__(self, request):
        if isinstance(request, GetPasswordRequest):
            return _Pwd()
        raise NotImplementedError

    async def iter_dialogs(self):
        for d in (
            _Dialog(-1001111111111, "Fake Channel", Channel(True, "fake_channel")),
            _Dialog(-1002222222222, "Fake Supergroup", Channel(False)),
            _Dialog(-333, "Fake Group", Chat()),
            _Dialog(444444444, "Fake Bot", User(bot=True, username="fake_bot")),
            _Dialog(555555555, "Fake Person", User(first_name="P"), archived=True),
        ):
            yield d
