"""Fail if the repository contains Telegram credentials or session files.

Run in CI on every push. Test fixtures use the obviously fake api_hash below.
"""

import re
import subprocess
import sys
from pathlib import Path

FAKE_HEX = {"0123456789abcdef0123456789abcdef"}
FORBIDDEN_NAMES = re.compile(r"(^|/)(\.env|[^/]+\.session|[^/]+\.session-journal)$")
HEX32 = re.compile(r"\b[0-9a-f]{32}\b")
STRING_SESSION = re.compile(r"\b1[A-Za-z0-9_\-]{300,}={0,2}")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f]


def main() -> int:
    problems = []
    for name in tracked_files():
        if FORBIDDEN_NAMES.search(name):
            problems.append(f"{name}: credential/session file must not be committed")
            continue
        path = Path(name)
        if path.suffix.lower() in {".png", ".ico", ".jpg", ".gif", ".zip"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in HEX32.finditer(text):
            if m.group(0) not in FAKE_HEX:
                problems.append(f"{name}: 32-char hex value (api_hash?) {m.group(0)[:6]}…")
        if STRING_SESSION.search(text):
            problems.append(f"{name}: looks like a Telethon string session")
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
