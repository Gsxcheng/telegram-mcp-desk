from tgmcp_desk.core.allowlist import (
    Dialog,
    bare_id,
    format_tokens,
    initial_selection,
    parse,
    token_matches,
)

DIALOGS = [
    Dialog("-1001111111111", "Example Channel", "channel", "example_channel"),
    Dialog("-2222", "Small Group", "group"),
    Dialog("3333333", "Some Bot", "bot", "some_bot"),
]


def test_bare_id():
    assert bare_id("-1001234567") == "1234567"
    assert bare_id("-1234") == "1234"
    assert bare_id("1234") == "1234"
    assert bare_id("@name") is None


def test_token_matches_all_spellings():
    ch = DIALOGS[0]
    for t in ["-1001111111111", "1111111111", "@Example_Channel", "example_channel"]:
        assert token_matches(t, ch), t
    assert not token_matches("@other", ch)


def test_parse_and_format():
    assert parse(" a, ,b,") == ["a", "b"]
    assert parse(None) == []
    assert format_tokens(["a", "b", "a", " "]) == "a,b"


def test_initial_selection_keeps_orphans():
    checked, orphans = initial_selection(["@example_channel", "-2222", "@gone_chat"], DIALOGS)
    assert checked == {"-1001111111111", "-2222"}
    assert orphans == ["@gone_chat"]
