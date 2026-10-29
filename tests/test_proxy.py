import socket
import struct
import threading

import pytest

from tgmcp_desk.core.proxy import ProxyConfig, ProxyTestError, check_proxy, detect_local_proxies

TARGET = ("149.154.167.51", 443)


def _serve_once(handler):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def run():
        conn, _ = srv.accept()
        with conn:
            handler(conn)
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return port


def _recv(conn, n):
    buf = b""
    while len(buf) < n:
        buf += conn.recv(n - len(buf))
    return buf


def socks5_ok(conn, expect_auth=None):
    ver, n = _recv(conn, 2)
    methods = _recv(conn, n)
    if expect_auth:
        assert 2 in methods
        conn.sendall(b"\x05\x02")
        _recv(conn, 1)
        ulen = _recv(conn, 1)[0]
        user = _recv(conn, ulen)
        plen = _recv(conn, 1)[0]
        pw = _recv(conn, plen)
        conn.sendall(b"\x01\x00" if (user, pw) == expect_auth else b"\x01\x01")
        if (user, pw) != expect_auth:
            return
    else:
        conn.sendall(b"\x05\x00")
    head = _recv(conn, 4)
    assert head[:3] == b"\x05\x01\x00" and head[3] == 1
    ip = socket.inet_ntoa(_recv(conn, 4))
    (port,) = struct.unpack(">H", _recv(conn, 2))
    assert (ip, port) == TARGET
    conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 6)


def test_socks5_success():
    port = _serve_once(socks5_ok)
    assert "可用" in check_proxy(ProxyConfig("socks5", "127.0.0.1", port), TARGET, timeout=3)


def test_socks5_auth_failure():
    port = _serve_once(lambda c: socks5_ok(c, expect_auth=(b"u", b"right")))
    with pytest.raises(ProxyTestError, match="用户名或密码"):
        check_proxy(ProxyConfig("socks5", "127.0.0.1", port, "u", "wrong"), TARGET, timeout=3)


def test_socks5_rejected():
    def handler(conn):
        _recv(conn, 3)
        conn.sendall(b"\x05\x00")
        _recv(conn, 10)
        conn.sendall(b"\x05\x05\x00\x01" + b"\x00" * 6)

    port = _serve_once(handler)
    with pytest.raises(ProxyTestError, match="错误码 5"):
        check_proxy(ProxyConfig("socks5", "127.0.0.1", port), TARGET, timeout=3)


def test_http_connect_success_and_wrong_protocol():
    def http_ok(conn):
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(1024)
        assert data.startswith(b"CONNECT 149.154.167.51:443 HTTP/1.1")
        conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")

    port = _serve_once(http_ok)
    assert "可用" in check_proxy(ProxyConfig("http", "127.0.0.1", port), TARGET, timeout=3)

    # A SOCKS5 port probed as HTTP gets a non-HTTP answer.
    port = _serve_once(lambda c: (c.recv(1024), c.sendall(b"\x05\xff")))
    with pytest.raises(ProxyTestError, match="不是 HTTP"):
        check_proxy(ProxyConfig("http", "127.0.0.1", port), TARGET, timeout=3)


def test_unreachable_proxy():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(ProxyTestError, match="连不上代理"):
        check_proxy(ProxyConfig("socks5", "127.0.0.1", port), TARGET, timeout=1)


def test_validate_and_env_roundtrip():
    assert ProxyConfig("mtproxy", "h", 443).validate() == ["MTProxy 需要填写 secret"]
    cfg = ProxyConfig("socks5", "127.0.0.1", 7897, "u", "p", rdns=False)
    env = {k: v for k, v in cfg.to_env().items() if v is not None}
    assert ProxyConfig.from_env(env) == cfg
    off = ProxyConfig().to_env()
    assert all(v is None for v in off.values())
    assert ProxyConfig.from_env({}) == ProxyConfig()


def test_detect_local_proxies():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    port = s.getsockname()[1]
    try:
        assert detect_local_proxies((port,)) == [port]
    finally:
        s.close()
