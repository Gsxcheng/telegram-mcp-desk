from tgmcp_desk.core.envfile import EnvFile, quote_value


def test_get_last_assignment_and_quotes():
    env = EnvFile.from_text("# comment\nA=1\nB=\"x y\"\nA=2\nC='raw\\n'\nD=v # note\n")
    assert env.get("A") == "2"
    assert env.get("B") == "x y"
    assert env.get("C") == "raw\\n"
    assert env.get("D") == "v"
    assert env.get("MISSING", "d") == "d"


def test_set_replaces_first_and_drops_duplicates_keeping_comments():
    env = EnvFile.from_text("# head\nA=1\n# mid\nA=2\nB=3\n")
    env.set("A", "9")
    assert env.lines == ["# head", "A=9", "# mid", "B=3"]
    env.set("NEW", "v")
    assert env.lines[-1] == "NEW=v"


def test_update_none_removes():
    env = EnvFile.from_text("A=1\nB=2\n")
    env.update({"A": None, "C": "3"})
    assert env.keys() == ["B", "C"]


def test_unset_prefix_keeps_listed():
    env = EnvFile.from_text("TELEGRAM_PROXY_TYPE=socks5\nTELEGRAM_PROXY_HOST=h\nX=1\n")
    env.unset_prefix("TELEGRAM_PROXY_", keep=["TELEGRAM_PROXY_HOST"])
    assert env.keys() == ["TELEGRAM_PROXY_HOST", "X"]


def test_quote_roundtrip():
    for value in ["plain", "with space", 'q"uote', "back\\slash", "has#hash", ""]:
        env = EnvFile.from_text(f"K={quote_value(value)}\n")
        assert env.get("K") == value


def test_save_writes_backup_and_keeps_crlf(tmp_path):
    p = tmp_path / ".env"
    p.write_bytes(b"\xef\xbb\xbfA=1\r\nB=2\r\n")
    env = EnvFile.load(p)
    assert env.get("A") == "1"
    env.set("A", "5")
    env.save()
    assert p.read_bytes() == b"A=5\r\nB=2\r\n"
    assert (tmp_path / ".env.bak").read_bytes().endswith(b"A=1\r\nB=2\r\n")


def test_load_missing_file(tmp_path):
    env = EnvFile.load(tmp_path / ".env")
    assert env.lines == []
    env.set("A", "1")
    env.save()
    assert (tmp_path / ".env").read_text().strip() == "A=1"
    assert not (tmp_path / ".env.bak").exists()
