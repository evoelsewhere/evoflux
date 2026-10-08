from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable

import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend
from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkStream


def _safe_destination(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return _safe_destination(address.ipv4_mapped)
    if address.is_loopback:
        return True
    if isinstance(address, ipaddress.IPv4Address):
        private_ranges = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("100.64.0.0/10"),  # Tailscale and RFC 6598 shared address space.
        )
        if any(address in network for network in private_ranges):
            return True
    elif address in ipaddress.ip_network("fc00::/7"):
        return True
    return address.is_global


class _PinnedDNSBackend:
    """Resolve once, validate every answer, then connect to the chosen IP literal.

    httpcore still owns TLS and receives the original request hostname, so SNI and
    certificate verification are preserved. The socket itself never re-resolves
    the hostname after this policy check.
    """

    def __init__(self, *, private_hosts: set[str], private_only: bool) -> None:
        self._delegate = AnyIOBackend()
        self._private_hosts = private_hosts
        self._private_only = private_only

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        normalized_host = host.lower().rstrip(".")
        require_private = self._private_only or normalized_host in self._private_hosts
        try:
            loop = asyncio.get_running_loop()
            resolve = loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            records = await asyncio.wait_for(resolve, timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise httpcore.ConnectTimeout("The configured STT endpoint resolution timed out.") from exc
        except OSError as exc:
            raise httpcore.ConnectError("The configured STT endpoint could not be resolved safely.") from exc

        try:
            candidates = validate_resolved_addresses(
                records,
                require_private=require_private,
                require_public=not require_private,
            )
        except OSError as exc:
            raise httpcore.ConnectError(str(exc)) from exc

        last_error: Exception | None = None
        for address in candidates:
            # Strip an IPv6 scope identifier; scoped/link-local addresses are
            # rejected by _safe_destination before reaching this point.
            pinned_address = address.split("%", 1)[0]
            try:
                return await self._delegate.connect_tcp(
                    pinned_address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout, OSError) as exc:
                last_error = exc
        raise last_error or OSError("The configured STT endpoint could not be reached.")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        return await self._delegate.connect_unix_socket(path, timeout=timeout, socket_options=socket_options)

    async def sleep(self, seconds: float) -> None:
        await self._delegate.sleep(seconds)


def validate_resolved_addresses(
    records,
    *,
    require_private: bool,
    require_public: bool = False,
) -> list[str]:
    candidates: list[str] = []
    for family, _socktype, _protocol, _canonical_name, sockaddr in records:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        raw_address = sockaddr[0]
        address = ipaddress.ip_address(raw_address.split("%", 1)[0])
        if not _safe_destination(address):
            raise OSError("The configured STT endpoint resolves to a restricted network address.")
        is_private = _safe_destination(address) and not address.is_global
        if require_private and not is_private:
            raise OSError("This voice profile is restricted to local or private network endpoints.")
        mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
        is_public = mapped.is_global if mapped else address.is_global
        if require_public and not is_public:
            raise OSError("A hosted STT endpoint must resolve only to public IP addresses.")
        if raw_address not in candidates:
            candidates.append(raw_address)
    if not candidates:
        raise OSError("The configured STT endpoint has no safe TCP addresses.")
    return candidates


def create_voice_http_client(*, private_hosts: set[str], private_only: bool) -> httpx.AsyncClient:
    client = httpx.AsyncClient(follow_redirects=False, trust_env=False)
    # httpx currently does not expose httpcore's supported network_backend
    # constructor argument. The pool hook lets DNS pinning retain HTTPX's SSL,
    # connection-pool, timeout, and HTTP parsing behavior.
    pool = client._transport._pool  # type: ignore[attr-defined]
    if not isinstance(pool, httpcore.AsyncConnectionPool):
        client._transport.close()  # type: ignore[attr-defined]
        raise RuntimeError("Voice endpoint pinning requires a direct HTTP connection pool.")
    pool._network_backend = _PinnedDNSBackend(  # type: ignore[attr-defined]
        private_hosts=private_hosts,
        private_only=private_only,
    )
    return client
