"""List the MCP tools an installed telegram-mcp registers, without running it.

The tools are found by parsing ``telegram_mcp/tools/*.py`` and looking for
functions decorated with ``@mcp.tool(...)``. A tool counts as read-only when
its decorator sets ``readOnlyHint=True`` -- the same flag telegram-mcp's
``read-only`` mode uses. Nothing from the scanned files is imported or executed.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Module names shown in the tools dialog.
MODULE_LABELS = {
    "accounts": "账号",
    "chats": "聊天",
    "contacts": "通讯录",
    "custom_emoji": "自定义表情",
    "events": "实时消息",
    "folders": "聊天文件夹",
    "groups": "群组管理",
    "media": "媒体",
    "messages": "消息",
    "profile": "个人资料",
    "stickers": "贴纸",
}


@dataclass(frozen=True)
class ToolInfo:
    name: str
    module: str
    read_only: bool
    title: str = ""


def _tool_decorator(dec: ast.expr) -> ast.Call | None:
    if isinstance(dec, ast.Call):
        func = dec.func
        if isinstance(func, ast.Attribute) and func.attr == "tool":
            return dec
        if isinstance(func, ast.Name) and func.id == "tool":
            return dec
    return None


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _annotation_info(call: ast.Call) -> tuple[bool, str]:
    ann = _kw(call, "annotations")
    read_only = False
    title = ""
    if isinstance(ann, ast.Call):
        ro = _kw(ann, "readOnlyHint")
        read_only = isinstance(ro, ast.Constant) and ro.value is True
        t = _kw(ann, "title")
        if isinstance(t, ast.Constant) and isinstance(t.value, str):
            title = t.value
    return read_only, title


def scan_source(source: str, module: str) -> list[ToolInfo]:
    tree = ast.parse(source)
    found: list[ToolInfo] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            call = _tool_decorator(dec)
            if call is None:
                continue
            name_kw = _kw(call, "name")
            name = node.name
            if isinstance(name_kw, ast.Constant) and isinstance(name_kw.value, str):
                name = name_kw.value
            read_only, title = _annotation_info(call)
            found.append(ToolInfo(name, module, read_only, title))
            break
    return found


def scan_install(install_dir: Path) -> list[ToolInfo]:
    tools_dir = Path(install_dir) / "telegram_mcp" / "tools"
    out: list[ToolInfo] = []
    for path in sorted(tools_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        out.extend(scan_source(path.read_text(encoding="utf-8"), path.stem))
    return out


def as_flags(tools: list[ToolInfo]) -> dict[str, bool]:
    return {t.name: t.read_only for t in tools}
