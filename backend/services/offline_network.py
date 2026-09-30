"""Fail closed on non-local Python socket traffic in private offline mode."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

_installed = False
_getaddrinfo = socket.getaddrinfo
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex
_sendto = socket.socket.sendto


def _is_local_host(host: Any) -> bool:
    if host is None or host == "":
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="ignore")
    host = str(host).strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_address(address: Any) -> None:
    # Unix-domain socket paths stay on the machine.
    if isinstance(address, (str, bytes)):
        return
    if isinstance(address, tuple) and address and _is_local_host(address[0]):
        return
    raise OSError(f"OFFLINE_MODE blocked a non-local network connection: {address!r}")


def install_offline_network_guard() -> None:
    """Allow localhost services and reject external DNS, TCP and UDP attempts."""
    global _installed
    if _installed:
        return

    def guarded_getaddrinfo(host, *args, **kwargs):
        if not _is_local_host(host):
            raise OSError(f"OFFLINE_MODE blocked external DNS lookup: {host!r}")
        return _getaddrinfo(host, *args, **kwargs)

    def guarded_connect(sock, address):
        _check_address(address)
        return _connect(sock, address)

    def guarded_connect_ex(sock, address):
        _check_address(address)
        return _connect_ex(sock, address)

    def guarded_sendto(sock, data, *args):
        if args:
            _check_address(args[-1])
        return _sendto(sock, data, *args)

    socket.getaddrinfo = guarded_getaddrinfo
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.socket.sendto = guarded_sendto
    _installed = True
