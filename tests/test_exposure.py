import pytest

from tgmcp_desk.core.exposure import (
    ACCOUNT_WIDE_TOOLS,
    ExposureError,
    ExposurePolicy,
    from_selection,
    privacy_preset,
)

TOOLS = {
    "list_chats": True,
    "get_messages": True,
    "list_contacts": True,
    "search_global": True,
    "send_message": False,
    "delete_messages_bulk": False,
}


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, ExposurePolicy("all")),
        ("all", ExposurePolicy("all")),
        ("READ-ONLY", ExposurePolicy("read-only")),
        ("read-only+send_message", ExposurePolicy("read-only", ("send_message",))),
        (
            "read-only-list_contacts,search_global",
            ExposurePolicy("read-only", (), ("list_contacts", "search_global")),
        ),
        (
            "read-only+send_message-list_contacts",
            ExposurePolicy("read-only", ("send_message",), ("list_contacts",)),
        ),
        ("all-delete_messages_bulk", ExposurePolicy("all", (), ("delete_messages_bulk",))),
    ],
)
def test_parse(value, expected):
    assert ExposurePolicy.parse(value) == expected


@pytest.mark.parametrize(
    "value",
    ["readonly", "all+send_message", "read-only+", "read-only-", "read-only+a-a", "none"],
)
def test_parse_rejects(value):
    with pytest.raises(ExposureError):
        ExposurePolicy.parse(value)


def test_str_roundtrip():
    for v in ["all", "read-only", "read-only+a,b-c", "all-x"]:
        assert str(ExposurePolicy.parse(v)) == v


def test_problems_unknown_and_already_hidden():
    p = ExposurePolicy.parse("read-only+nope-send_message,ghost")
    probs = p.problems(TOOLS)
    assert any("nope" in x for x in probs)
    assert any("ghost" in x for x in probs)
    assert any("send_message" in x and "已被" in x for x in probs)
    assert ExposurePolicy.parse("read-only-list_contacts").problems(TOOLS) == []


def test_exposed():
    p = ExposurePolicy.parse("read-only+send_message-list_contacts")
    assert p.exposed(TOOLS) == {"list_chats", "get_messages", "search_global", "send_message"}


def test_from_selection_is_valid_and_exact():
    sel = {"list_chats", "send_message"}
    p = from_selection(TOOLS, sel)
    assert p.problems(TOOLS) == []
    assert p.exposed(TOOLS) == sel
    assert str(p) == "read-only+send_message-get_messages,list_contacts,search_global"


def test_from_selection_without_writes_has_no_plus():
    p = from_selection(TOOLS, {"list_chats", "get_messages", "list_contacts", "search_global"})
    assert str(p) == "read-only"


def test_privacy_preset_hides_only_existing_account_wide_tools():
    p = privacy_preset(TOOLS)
    assert p.problems(TOOLS) == []
    assert set(p.exclude) == {"list_contacts", "search_global"}
    assert p.exposed(TOOLS) == {"list_chats", "get_messages"}
    assert set(p.exclude) <= set(ACCOUNT_WIDE_TOOLS)
