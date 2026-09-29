"""Upstream public-address validation, retained for every outbound URL and redirect."""

import ipaddress
import socket
from urllib.parse import urlparse

# RFC 1918 + loopback private ranges to block SSRF
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),  # 0.0.0.0 reaches localhost on Linux
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT / Shared Address Space
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def _is_blocked_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if an address is anything other than a routable public destination.

    The explicit `_PRIVATE_NETS` list is kept for readability, but the stdlib
    properties are the real gate — they also cover 0.0.0.0/8 (which reaches
    localhost on Linux), CGNAT, benchmark, multicast and reserved space.
    """
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        # ::ffff:192.168.1.1 must be judged as the v4 address it wraps.
        addr = addr.ipv4_mapped
    if any(addr in net for net in _PRIVATE_NETS):
        return True
    # `is_global` is the precise question being asked — is this routable on the
    # public internet. Do not swap it for `is_private`: the stdlib deliberately
    # reports 100.64.0.0/10 (CGNAT) as non-private since 3.12.4, so `is_private`
    # alone lets Shared Address Space through. Multicast and reserved space are
    # checked separately because they are absent from the IANA special registry
    # that backs `is_global`, which therefore reports them as global.
    return not addr.is_global or addr.is_multicast or addr.is_reserved


def _resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to every address it maps to.

    Separated out so tests can patch it without needing live DNS.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"could not resolve host: {host}") from e

    addrs = []
    for info in infos:
        # Strip any IPv6 scope id (fe80::1%eth0) before parsing.
        raw = info[4][0].split("%")[0]
        try:
            addrs.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    return addrs


def _validate_url(url: str) -> None:
    """Reject non-https URLs and any destination that is not a public address.

    A hostname is resolved and *every* address it maps to is checked — checking
    only literal-IP hosts leaves `https://name-that-resolves-to-10.0.0.1/` wide
    open. Callers must re-run this against each redirect target as well; see
    `_fetch_raw`.

    Residual risk: this is a resolve-then-connect check, so a DNS entry that
    changes between validation and the HTTP client's own lookup (DNS rebinding)
    is not caught. Closing that fully requires pinning the connection to the
    validated address; not done here.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"URL scheme '{parsed.scheme}' not allowed — must be https")

    host = parsed.hostname or ""
    if not host:
        raise ValueError("URL has no host")

    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        addrs = _resolve_host(host)

    if not addrs:
        raise ValueError(f"could not resolve host: {host}")

    for addr in addrs:
        if _is_blocked_address(addr):
            raise ValueError(f"URL resolves to private/loopback address: {addr}")
