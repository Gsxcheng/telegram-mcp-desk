"""Build and check ``TELEGRAM_EXPOSED_TOOLS`` values.

telegram-mcp aborts at startup when this value names an unknown tool, or
excludes a tool its base mode already hides. These helpers mirror those rules
(chigwell/telegram-mcp ``runtime._parse_exposed_tools_mode`` /
``_apply_exposed_tools_mode``) so the manager never writes a value that stops
the server from starting.

Format: ``<base>[+allow,allow][-exclude,exclude]`` where base is ``all`` or
``read-only``; ``+`` is only valid after ``read-only``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

BASES = ("all", "read-only")

# Read-only tools that reach beyond the chat allowlist into the whole account
# (address book, drafts, folders, global search...). The allowlist in
# TELEGRAM_ALLOWED_CHAT_IDS does not cover them, so the privacy preset hides
# them. Names that do not exist in the installed version are skipped.
ACCOUNT_WIDE_TOOLS: dict[str, str] = {
    "list_contacts": "通讯录",
    "search_contacts": "通讯录",
    "get_contact_ids": "通讯录",
    "get_direct_chat_by_contact": "通讯录",
    "get_contact_chats": "通讯录",
    "get_last_interaction": "通讯录",
    "export_contacts": "通讯录",
    "list_contact_aliases": "通讯录",
    "get_blocked_users": "黑名单",
    "get_drafts": "草稿",
    "search_global": "全局搜索",
    "search_public_chats": "公开搜索",
    "get_common_chats": "共同群组",
    "get_privacy_settings": "隐私设置",
    "list_folders": "聊天文件夹",
    "get_folder": "聊天文件夹",
    "get_folder_snapshot": "聊天文件夹",
}


class ExposureError(ValueError):
    """The value would make telegram-mcp refuse to start."""


@dataclass(frozen=True)
class ExposurePolicy:
    base: str = "all"
    allow: tuple[str, ...] = field(default_factory=tuple)
    exclude: tuple[str, ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        out = self.base
        if self.allow:
            out += "+" + ",".join(self.allow)
        if self.exclude:
            out += "-" + ",".join(self.exclude)
        return out

    @classmethod
    def parse(cls, value: str | None) -> ExposurePolicy:
        """Parse a value the same way telegram-mcp does (syntax only)."""
        raw = (value or "all").strip().lower()
        for base in sorted(BASES, key=len, reverse=True):
            rest = raw[len(base) :]
            if raw.startswith(base) and rest[:1] in ("", "+", "-"):
                break
        else:
            raise ExposureError(
                f"无法识别的 TELEGRAM_EXPOSED_TOOLS：{value!r}（应以 all 或 read-only 开头）"
            )

        allow_raw: str | None = None
        exclude_raw: str | None = None
        if rest.startswith("+"):
            allow_raw, sep, tail = rest[1:].partition("-")
            if sep:
                exclude_raw = tail
        elif rest.startswith("-"):
            exclude_raw = rest[1:]

        allow = _split(allow_raw)
        exclude = _split(exclude_raw)
        if allow is not None and base != "read-only":
            raise ExposureError("“+工具名”只能跟在 read-only 后面")
        if allow is not None and not allow:
            raise ExposureError("“+” 后面至少要写一个工具名")
        if exclude is not None and not exclude:
            raise ExposureError("“-” 后面至少要写一个工具名")
        both = sorted(set(allow or ()) & set(exclude or ()))
        if both:
            raise ExposureError("同一个工具既放行又屏蔽：" + ", ".join(both))
        return cls(base, tuple(allow or ()), tuple(exclude or ()))

    # -- semantics -----------------------------------------------------------

    def base_exposes(self, name: str, read_only: bool) -> bool:
        return self.base == "all" or read_only or name in self.allow

    def exposed(self, tools: Mapping[str, bool]) -> set[str]:
        """Names that end up registered, given ``{tool_name: is_read_only}``."""
        excluded = set(self.exclude)
        return {
            name
            for name, ro in tools.items()
            if self.base_exposes(name, ro) and name not in excluded
        }

    def problems(self, tools: Mapping[str, bool]) -> list[str]:
        """Reasons telegram-mcp would refuse this value; empty list means OK."""
        out: list[str] = []
        unknown_allow = sorted(set(self.allow) - set(tools))
        if unknown_allow:
            out.append("放行列表里有不存在的工具：" + ", ".join(unknown_allow))
        unknown_ex = sorted(set(self.exclude) - set(tools))
        if unknown_ex:
            out.append("屏蔽列表里有不存在的工具：" + ", ".join(unknown_ex))
        already = sorted(
            n for n in self.exclude if n in tools and not self.base_exposes(n, tools[n])
        )
        if already:
            out.append(f"这些工具已被 {self.base} 隐藏，不能再写进屏蔽列表：" + ", ".join(already))
        return out


def _split(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def from_selection(tools: Mapping[str, bool], selected: Iterable[str]) -> ExposurePolicy:
    """Smallest valid policy that exposes exactly ``selected``.

    If any write tool is selected the policy is ``read-only+<writes>``; read-only
    tools that are not selected go into the ``-`` list. With no write tools the
    ``+`` list is omitted.
    """
    chosen = set(selected)
    unknown = chosen - set(tools)
    if unknown:
        raise ExposureError("不存在的工具：" + ", ".join(sorted(unknown)))
    writes = sorted(n for n in chosen if not tools[n])
    hidden_ro = sorted(n for n, ro in tools.items() if ro and n not in chosen)
    return ExposurePolicy("read-only", tuple(writes), tuple(hidden_ro))


def privacy_preset(tools: Mapping[str, bool]) -> ExposurePolicy:
    """Read-only tools minus the account-wide ones that exist in this version."""
    selected = [n for n, ro in tools.items() if ro and n not in ACCOUNT_WIDE_TOOLS]
    return from_selection(tools, selected)
