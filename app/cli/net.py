"""Network helpers for CLI server address display and probes."""

from __future__ import annotations

import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerAddresses:
    local: str
    lan: list[str]


def _format_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}"


def _lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = str(info[4][0])
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass

    return sorted(ips)


def server_addresses(*, host: str, port: int) -> ServerAddresses:
    lan = [f"http://{ip}:{port}" for ip in _lan_ips()]
    return ServerAddresses(local=_format_url(host, port), lan=lan)


def is_port_reachable(*, host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
