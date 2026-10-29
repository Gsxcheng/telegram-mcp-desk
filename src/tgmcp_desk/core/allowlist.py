"""Chat allowlist (``TELEGRAM_ALLOWED_CHAT_IDS``) helpers.

The value is a comma-separated list of numeric IDs or ``@usernames``. Numeric
IDs come in several spellings for the same chat (``-1001234``, ``-1234``,
``1234``); they are compared on their bare digits.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

ENV_KEY = "TELEGRAM_ALLOWED_CHAT_IDS"

_CHANNEL_RE = re.compile(r"^-100(\d+)$")
_NUMERIC_RE = re.compile(r"^-?(\d+)$")


@dataclass(frozen=True)
class Dialog:
    """One chat as reported by the dialogs helper."""

    id: str
    name: str
    kind: str  # channel | group | bot | user | other
    username: str = ""
    archived: bool = False


KIND_LABELS = {
    "channel": "频道",
    "group": "群组",
    "bot": "机器人",
    "user": "私聊",
    "other": "其他",
    "unknown": "?",
}


def bare_id(token: str) -> str | None:
    token = token.strip()
    m = _CHANNEL_RE.match(token) or _NUMERIC_RE.match(token)
    return m.group(1) if m else None


def parse(value: str | None) -> list[str]:
    if not value:
        return []
    return [t.strip() for t in value.split(",") if t.strip()]


def format_tokens(tokens: Iterable[str]) -> str:
    seen: list[str] = []
    for t in tokens:
        t = t.strip()
        if t and t not in seen:
            seen.append(t)
    return ",".join(seen)


def token_matches(token: str, dialog: Dialog) -> bool:
    bare = bare_id(token)
    if bare is not None:
        return bare == bare_id(dialog.id)
    handle = token.strip().lstrip("@").lower()
    return bool(dialog.username) and handle == dialog.username.lower()


def initial_selection(
    current: Iterable[str], dialogs: Iterable[Dialog]
) -> tuple[set[str], list[str]]:
    """Map the current allowlist onto dialogs.

    Returns ``(checked_dialog_ids, orphans)``: dialog IDs to pre-check, and tokens
    that match no dialog (left chats, typos). Orphans are kept so a save never
    silently drops them; the UI shows them as checked rows.
    """
    dialogs = list(dialogs)
    checked: set[str] = set()
    orphans: list[str] = []
    for token in current:
        hits = [d.id for d in dialogs if token_matches(token, d)]
        if hits:
            checked.update(hits)
        else:
            orphans.append(token)
    return checked, orphans
