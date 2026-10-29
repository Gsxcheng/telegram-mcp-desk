"""Read and edit telegram-mcp's ``.env`` without disturbing what the user wrote.

The file is edited line by line: comments, blank lines and the order of keys
are kept, only the lines for keys we set are touched. Every save writes a
``.env.bak`` copy of the previous version first.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path

_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
# Characters that force a value into double quotes so python-dotenv reads it back verbatim.
_NEEDS_QUOTES_RE = re.compile(r"[\s#'\"\\$]")


def _unquote(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        if value[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    # Unquoted: an inline comment starts at " #".
    hash_at = value.find(" #")
    if hash_at != -1:
        value = value[:hash_at].rstrip()
    return value


def quote_value(value: str) -> str:
    """Return ``value`` as it should appear after ``KEY=``."""
    if value == "" or not _NEEDS_QUOTES_RE.search(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class EnvFile:
    """An editable view of a dotenv file."""

    def __init__(self, path: Path, lines: list[str] | None = None, newline: str = "\n"):
        self.path = Path(path)
        self.lines: list[str] = lines if lines is not None else []
        self.newline = newline

    @classmethod
    def load(cls, path: Path) -> EnvFile:
        path = Path(path)
        if not path.exists():
            return cls(path, [], os.linesep if os.name == "nt" else "\n")
        raw = path.read_bytes().decode("utf-8-sig")
        newline = "\r\n" if "\r\n" in raw else "\n"
        return cls(path, raw.splitlines(), newline)

    @classmethod
    def from_text(cls, text: str, path: Path | str = ".env") -> EnvFile:
        newline = "\r\n" if "\r\n" in text else "\n"
        return cls(Path(path), text.splitlines(), newline)

    # -- reading -------------------------------------------------------------

    def get(self, key: str, default: str | None = None) -> str | None:
        """Value of the last assignment of ``key`` (python-dotenv semantics)."""
        found = default
        for line in self.lines:
            m = _KEY_RE.match(line)
            if m and m.group(1) == key:
                found = _unquote(m.group(2))
        return found

    def keys(self) -> list[str]:
        out: list[str] = []
        for line in self.lines:
            m = _KEY_RE.match(line)
            if m and m.group(1) not in out:
                out.append(m.group(1))
        return out

    def as_dict(self) -> dict[str, str]:
        return {k: self.get(k) or "" for k in self.keys()}

    # -- editing -------------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        """Set ``key``: replace its first assignment, drop later duplicates."""
        new_line = f"{key}={quote_value(value)}"
        out: list[str] = []
        replaced = False
        for line in self.lines:
            m = _KEY_RE.match(line)
            if m and m.group(1) == key:
                if not replaced:
                    out.append(new_line)
                    replaced = True
                continue
            out.append(line)
        if not replaced:
            out.append(new_line)
        self.lines = out

    def update(self, values: Mapping[str, str | None]) -> None:
        """Set several keys; a ``None`` value removes the key."""
        for key, value in values.items():
            if value is None:
                self.unset(key)
            else:
                self.set(key, value)

    def unset(self, key: str) -> None:
        self.lines = [
            line for line in self.lines if not ((m := _KEY_RE.match(line)) and m.group(1) == key)
        ]

    def unset_prefix(self, prefix: str, keep: Iterable[str] = ()) -> None:
        keep_set = set(keep)
        self.lines = [
            line
            for line in self.lines
            if not (
                (m := _KEY_RE.match(line))
                and m.group(1).startswith(prefix)
                and m.group(1) not in keep_set
            )
        ]

    # -- writing -------------------------------------------------------------

    def text(self) -> str:
        if not self.lines:
            return ""
        return self.newline.join(self.lines) + self.newline

    def save(self, backup: bool = True) -> None:
        """Write the file (UTF-8, no BOM), keeping the previous one as ``.env.bak``."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if backup and self.path.exists():
            shutil.copy2(self.path, self.path.with_name(self.path.name + ".bak"))
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_bytes(self.text().encode("utf-8"))
        os.replace(tmp, self.path)
