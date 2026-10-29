from tgmcp_desk.core.supervisor import RestartPolicy, RestartTracker, read_tail, rotate_log


def test_restart_then_give_up_after_fast_fails():
    t = RestartTracker(RestartPolicy(delay_seconds=30, fast_fail_seconds=60, max_fast_fails=3))
    now = 0.0
    for i in range(1, 3):
        t.on_started(now)
        d = t.on_exit(now + 5, auto_restart=True)
        assert d.restart_in == 30 and not d.gave_up and d.fast_fails == i
        now += 100
    t.on_started(now)
    d = t.on_exit(now + 5, auto_restart=True)
    assert d.gave_up and d.restart_in is None


def test_long_run_resets_streak():
    t = RestartTracker(RestartPolicy(max_fast_fails=2))
    t.on_started(0)
    t.on_exit(1, True)
    t.on_started(10)
    t.on_healthy(100)
    assert t.fast_fails == 0
    d = t.on_exit(500, True)
    assert d.fast_fails == 0 and d.restart_in is not None


def test_no_auto_restart():
    t = RestartTracker()
    t.on_started(0)
    d = t.on_exit(1, auto_restart=False)
    assert d.restart_in is None and not d.gave_up


def test_rotate_log(tmp_path):
    p = tmp_path / "x.log"
    assert not rotate_log(p, 10)
    p.write_bytes(b"a" * 5)
    assert not rotate_log(p, 10)
    p.write_bytes(b"a" * 20)
    assert rotate_log(p, 10)
    assert not p.exists() and (tmp_path / "x.log.old").stat().st_size == 20


def test_read_tail_follows_and_handles_rotation(tmp_path):
    p = tmp_path / "x.log"
    assert read_tail(p, 0) == ("", 0)
    p.write_bytes(b"one\n")
    text, off = read_tail(p, 0)
    assert text == "one\n"
    with p.open("ab") as f:
        f.write(b"two\n")
    text, off = read_tail(p, off)
    assert text == "two\n"
    p.write_bytes(b"new\n")  # rotated / truncated
    text, off = read_tail(p, off + 100)
    assert text == "new\n"
