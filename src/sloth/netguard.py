"""A tiny, loud airgap.

Sloth talks to exactly one thing: the llama.cpp server on localhost. This module
makes that a rule rather than a promise by rejecting any outbound connection to
a non-loopback address. No telemetry, no cloud fallback, no surprises.
"""
from __future__ import annotations

import ipaddress
import socket
import threading

_lock = threading.Lock()
_blocked = []
_installed = False
_original_connect = None
_original_create_connection = None


def _is_loopback(host) -> bool:
    if host in (None, "", "localhost"):
        return True
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii", "ignore")
        except Exception:
            return False
    if not isinstance(host, str):
        return False
    host = host.strip("[]").lower()
    if host in ("localhost", "localhost.localdomain", "::1", "0.0.0.0"):
        # 0.0.0.0 as a connect target still resolves to the local host.
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def install() -> None:
    """Patch socket so only loopback TCP is reachable from this process."""
    global _installed, _original_connect, _original_create_connection
    with _lock:
        if _installed:
            return
        _original_connect = socket.socket.connect
        _original_create_connection = socket.create_connection

        def guarded_connect(self, address):
            if self.family in (socket.AF_INET, socket.AF_INET6):
                host = address[0] if isinstance(address, tuple) else address
                if not _is_loopback(host):
                    _blocked.append(str(host))
                    raise PermissionError(
                        "Sloth is offline by design. Blocked a connection to %s. "
                        "Everything it needs is on this laptop." % host
                    )
            return _original_connect(self, address)

        def guarded_create_connection(address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) else address
            if not _is_loopback(host):
                _blocked.append(str(host))
                raise PermissionError(
                    "Sloth is offline by design. Blocked a connection to %s." % host
                )
            return _original_create_connection(address, *args, **kwargs)

        socket.socket.connect = guarded_connect
        socket.create_connection = guarded_create_connection
        _installed = True


def status() -> dict:
    with _lock:
        return {
            "active": _installed,
            "blocked": len(_blocked),
            "blocked_hosts": _blocked[-5:],
        }
