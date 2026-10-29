"""Strip secrets and personal identifiers before anything is shared.

Used for the diagnostics bundle users attach to GitHub issues. The rules err on
the side of removing too much: all credentials, session data, phone numbers,
chat IDs and usernames.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

REDACTED = "<已隐藏>"

# Keys whose values are always hidden.
_SECRET_KEY_RE = re.compile(
    r"(HASH|SESSION|PASSWORD|SECRET|TOKEN|PHONE|ALLOWED_CHAT_IDS|USERNAME|API_ID|"
    r"ALLOWED_HOSTS|EXPECTED_USER)",
    re.IGNORECASE,
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Telethon string sessions start with "1" and are long base64url.
    (re.compile(r"\b1[A-Za-z0-9_\-]{100,}={0,2}"), "<session>"),
    # Long hex such as api_hash or MTProxy secrets.
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "<hex>"),
    # International phone numbers.
    (re.compile(r"\+\d[\d \-]{6,}\d"), "<phone>"),
    # Channel / supergroup IDs and other long numeric IDs.
    (re.compile(r"-100\d{5,}"), "<chat_id>"),
    (re.compile(r"(?<![\d.:])\d{7,}(?![\d.])"), "<id>"),
    # @usernames.
    (re.compile(r"(?<![\w.])@[A-Za-z][A-Za-z0-9_]{3,}"), "@<user>"),
    # Windows user profile paths.
    (re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\s\"']+"), r"\1<user>"),
]


def redact_env(env: Mapping[str, str]) -> dict[str, str]:
    out = {}
    for key, value in env.items():
        if value and _SECRET_KEY_RE.search(key):
            out[key] = REDACTED
        else:
            out[key] = redact_text(value or "")
    return out


def redact_text(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
