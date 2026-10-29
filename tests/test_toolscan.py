from tgmcp_desk.core.toolscan import as_flags, scan_install, scan_source

SRC = """
from mcp.types import ToolAnnotations

@mcp.tool(annotations=ToolAnnotations(title="List Chats", readOnlyHint=True))
@with_account(readonly=True)
async def list_chats(): ...

@mcp.tool(annotations=ToolAnnotations(title="Send", destructiveHint=True))
async def send_message(): ...

@mcp.tool(name="renamed", annotations=ToolAnnotations(readOnlyHint=False))
def other(): ...

@other_decorator
async def helper(): ...

def plain(): ...
"""


def test_scan_source():
    tools = scan_source(SRC, "chats")
    assert [(t.name, t.read_only, t.title) for t in tools] == [
        ("list_chats", True, "List Chats"),
        ("send_message", False, "Send"),
        ("renamed", False, ""),
    ]


def test_scan_install(tmp_path):
    d = tmp_path / "telegram_mcp" / "tools"
    d.mkdir(parents=True)
    (d / "chats.py").write_text(SRC, encoding="utf-8")
    (d / "__init__.py").write_text("from .chats import *\n", encoding="utf-8")
    flags = as_flags(scan_install(tmp_path))
    assert flags == {"list_chats": True, "send_message": False, "renamed": False}
