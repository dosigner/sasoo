"""Prevent backend tests from connecting to external networks."""

import ipaddress
import socket

import pytest


_blocked_connections = 0


def _is_local_address(sock, address):
    if sock.family == socket.AF_UNIX:
        return True
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return False
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_socket_connections(monkeypatch):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def check(sock, address):
        global _blocked_connections
        if not _is_local_address(sock, address):
            _blocked_connections += 1
            raise RuntimeError("External socket connections are blocked in backend tests")

    def connect(sock, address):
        check(sock, address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check(sock, address)
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


def pytest_terminal_summary(terminalreporter):
    terminalreporter.write_line(f"External socket attempts blocked: {_blocked_connections}")
