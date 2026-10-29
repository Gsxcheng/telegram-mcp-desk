"""Proxy settings (``TELEGRAM_PROXY_*``), local proxy detection and a reachability test.

The test speaks just enough SOCKS5 / HTTP CONNECT to ask the proxy for a TCP
connection to a Telegram data center. It does not talk the Telegram protocol
and sends no account data.
"""

from __future__ import annotations

import base64
import ipaddress
import socket
import struct
from dataclasses import dataclass

TYPES = ("none", "socks5", "socks4", "http", "mtproxy")

# Mixed / SOCKS ports used by common desktop proxy clients
# (Clash and forks: 7890/7891/7897, v2rayN: 10808/10809, sing-box style: 2080).
COMMON_LOCAL_PORTS = (7890, 7897, 7891, 10808, 10809, 2080, 1080, 1081)

# A Telegram production data center (DC2) used only as a CONNECT target.
TELEGRAM_TEST_TARGET = ("149.154.167.51", 443)

ENV_KEYS = (
    "TELEGRAM_PROXY_TYPE",
    "TELEGRAM_PROXY_HOST",
    "TELEGRAM_PROXY_PORT",
    "TELEGRAM_PROXY_USERNAME",
    "TELEGRAM_PROXY_PASSWORD",
    "TELEGRAM_PROXY_RDNS",
    "TELEGRAM_PROXY_SECRET",
)


@dataclass
class ProxyConfig:
    type: str = "none"
    host: str = "127.0.0.1"
    port: int = 7890
    username: str = ""
    password: str = ""
    rdns: bool = True
    secret: str = ""

    @property
    def enabled(self) -> bool:
        return self.type != "none"

    def validate(self) -> list[str]:
        out: list[str] = []
        if self.type not in TYPES:
            out.append(f"不支持的代理类型：{self.type}")
        if not self.enabled:
            return out
        if not self.host.strip():
            out.append("代理地址不能为空")
        if not 1 <= int(self.port) <= 65535:
            out.append("代理端口应在 1～65535 之间")
        if self.type == "mtproxy" and not self.secret.strip():
            out.append("MTProxy 需要填写 secret")
        return out

    def to_env(self) -> dict[str, str | None]:
        """Values for EnvFile.update(); ``None`` removes the key."""
        if not self.enabled:
            return dict.fromkeys(ENV_KEYS)
        env: dict[str, str | None] = {
            "TELEGRAM_PROXY_TYPE": self.type,
            "TELEGRAM_PROXY_HOST": self.host.strip(),
            "TELEGRAM_PROXY_PORT": str(int(self.port)),
            "TELEGRAM_PROXY_USERNAME": self.username or None,
            "TELEGRAM_PROXY_PASSWORD": self.password or None,
            "TELEGRAM_PROXY_RDNS": None if self.rdns else "false",
            "TELEGRAM_PROXY_SECRET": None,
        }
        if self.type == "mtproxy":
            env.update(
                TELEGRAM_PROXY_USERNAME=None,
                TELEGRAM_PROXY_PASSWORD=None,
                TELEGRAM_PROXY_RDNS=None,
                TELEGRAM_PROXY_SECRET=self.secret.strip(),
            )
        return env

    @classmethod
    def from_env(cls, env: dict[str, str]) -> ProxyConfig:
        t = (env.get("TELEGRAM_PROXY_TYPE") or "").strip().lower()
        if not t:
            return cls()
        try:
            port = int(env.get("TELEGRAM_PROXY_PORT") or 0)
        except ValueError:
            port = 0
        rdns_raw = env.get("TELEGRAM_PROXY_RDNS")
        rdns = True if rdns_raw is None else rdns_raw.strip().lower() in {"1", "true", "yes", "on"}
        return cls(
            type=t,
            host=env.get("TELEGRAM_PROXY_HOST") or "",
            port=port,
            username=env.get("TELEGRAM_PROXY_USERNAME") or "",
            password=env.get("TELEGRAM_PROXY_PASSWORD") or "",
            rdns=rdns,
            secret=env.get("TELEGRAM_PROXY_SECRET") or "",
        )

    def http_url(self) -> str | None:
        """``http://host:port`` usable as HTTPS_PROXY for downloads (socks/mtproxy: None)."""
        if self.type != "http":
            return None
        return f"http://{self.host}:{int(self.port)}"


def detect_local_proxies(
    ports: tuple[int, ...] = COMMON_LOCAL_PORTS, host: str = "127.0.0.1", timeout: float = 0.25
) -> list[int]:
    """Ports among ``ports`` that accept TCP connections on ``host``."""
    found = []
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                found.append(port)
        except OSError:
            pass
    return found


class ProxyTestError(Exception):
    pass


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ProxyTestError("代理提前断开了连接")
        buf += chunk
    return buf


def _socks5_connect(sock: socket.socket, cfg: ProxyConfig, target: tuple[str, int]) -> None:
    methods = b"\x00\x02" if cfg.username else b"\x00"
    sock.sendall(b"\x05" + bytes([len(methods)]) + methods)
    ver, method = _recv_exact(sock, 2)
    if ver != 5:
        raise ProxyTestError("对方不是 SOCKS5 代理（端口可能是 HTTP 代理，试试类型选 http）")
    if method == 0x02:
        user = cfg.username.encode()
        pw = cfg.password.encode()
        sock.sendall(b"\x01" + bytes([len(user)]) + user + bytes([len(pw)]) + pw)
        if _recv_exact(sock, 2)[1] != 0:
            raise ProxyTestError("代理用户名或密码不对")
    elif method != 0x00:
        raise ProxyTestError("代理要求的认证方式不支持")
    host, port = target
    try:
        addr = b"\x01" + ipaddress.IPv4Address(host).packed
    except ValueError:
        addr = b"\x03" + bytes([len(host)]) + host.encode()
    sock.sendall(b"\x05\x01\x00" + addr + struct.pack(">H", port))
    head = _recv_exact(sock, 4)
    if head[1] != 0:
        raise ProxyTestError(f"代理拒绝连接 Telegram（SOCKS5 错误码 {head[1]}）")
    atyp = head[3]
    if atyp == 1:
        _recv_exact(sock, 4 + 2)
    elif atyp == 3:
        _recv_exact(sock, _recv_exact(sock, 1)[0] + 2)
    elif atyp == 4:
        _recv_exact(sock, 16 + 2)


def _socks4_connect(sock: socket.socket, cfg: ProxyConfig, target: tuple[str, int]) -> None:
    host, port = target
    ip = ipaddress.IPv4Address(host).packed
    sock.sendall(b"\x04\x01" + struct.pack(">H", port) + ip + cfg.username.encode() + b"\x00")
    reply = _recv_exact(sock, 8)
    if reply[1] != 0x5A:
        raise ProxyTestError("SOCKS4 代理拒绝连接 Telegram")


def _http_connect(sock: socket.socket, cfg: ProxyConfig, target: tuple[str, int]) -> None:
    host, port = target
    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if cfg.username:
        token = base64.b64encode(f"{cfg.username}:{cfg.password}".encode()).decode()
        req += f"Proxy-Authorization: Basic {token}\r\n"
    sock.sendall((req + "\r\n").encode())
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 8192:
        chunk = sock.recv(1024)
        if not chunk:
            break
        data += chunk
    status = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = status.split()
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise ProxyTestError("对方不是 HTTP 代理（端口可能是 SOCKS5，试试类型选 socks5）")
    if parts[1] != "200":
        raise ProxyTestError(f"HTTP 代理拒绝连接 Telegram：{status}")


def check_proxy(
    cfg: ProxyConfig, target: tuple[str, int] = TELEGRAM_TEST_TARGET, timeout: float = 8.0
) -> str:
    """Raise ProxyTestError on failure; return a short success message."""
    problems = cfg.validate()
    if problems:
        raise ProxyTestError("；".join(problems))
    if not cfg.enabled:
        try:
            with socket.create_connection(target, timeout=timeout):
                return "不用代理也能连上 Telegram"
        except OSError as exc:
            raise ProxyTestError(f"直连 Telegram 失败（{exc}），大概率需要代理") from exc
    try:
        sock = socket.create_connection((cfg.host, int(cfg.port)), timeout=timeout)
    except OSError as exc:
        raise ProxyTestError(
            f"连不上代理 {cfg.host}:{cfg.port}（{exc}），代理软件开着吗？"
        ) from exc
    with sock:
        sock.settimeout(timeout)
        try:
            if cfg.type == "socks5":
                _socks5_connect(sock, cfg, target)
            elif cfg.type == "socks4":
                _socks4_connect(sock, cfg, target)
            elif cfg.type == "http":
                _http_connect(sock, cfg, target)
            elif cfg.type == "mtproxy":
                return "能连上 MTProxy 服务器（secret 是否正确要登录时才能确认）"
        except TimeoutError as exc:
            raise ProxyTestError("代理没有响应（超时）") from exc
        except OSError as exc:
            raise ProxyTestError(f"代理连接出错：{exc}") from exc
    return "代理可用，能连到 Telegram 数据中心"
