import socket

from tgmcp_desk.core.ports import in_ranges, is_listening, parse_excluded_ranges, pick_port

NETSH = """
Protocol tcp Port Exclusion Ranges

Start Port    End Port
----------    --------
      8700        8799
     50000       50059     *

* - Administered port exclusions.
"""


def test_parse_excluded_ranges():
    assert parse_excluded_ranges(NETSH) == [(8700, 8799), (50000, 50059)]


def test_pick_port_skips_reserved_and_busy():
    ranges = [(8700, 8799)]
    assert pick_port(8765, ranges, bindable=lambda p: True) == 8800
    assert pick_port(18765, ranges, bindable=lambda p: p != 18765) == 18766
    assert not in_ranges(18765, ranges)


def test_is_listening():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    port = s.getsockname()[1]
    try:
        assert is_listening(port)
    finally:
        s.close()


def test_parse_netstat_listeners():
    from tgmcp_desk.core.ports import parse_netstat_listeners

    out = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1000
  TCP    127.0.0.1:18765        0.0.0.0:0              LISTENING       4242
  TCP    127.0.0.1:18765        127.0.0.1:50000        ESTABLISHED     4242
  TCP    [::1]:18765            [::]:0                 LISTENING       4242
  TCP    127.0.0.1:187650       0.0.0.0:0              LISTENING       7
"""
    assert parse_netstat_listeners(out, 18765) == [4242]
    assert parse_netstat_listeners(out, 135) == [1000]
