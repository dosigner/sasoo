import socket

import pytest


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_external_connection_is_blocked(method):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(RuntimeError, match="External socket connections are blocked"):
            getattr(client, method)(("192.0.2.1", 443))


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_loopback_connection_is_allowed(method):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            result = getattr(client, method)(server.getsockname())
            assert result in (None, 0)
            connection, _ = server.accept()
            connection.close()


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_ipv4_guard_works_without_unix_sockets(method, monkeypatch):
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        with pytest.raises(RuntimeError, match="External socket connections are blocked"):
            getattr(client, method)(("192.0.2.1", 443))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            assert getattr(client, method)(server.getsockname()) in (None, 0)
            connection, _ = server.accept()
            connection.close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Unix sockets are unavailable on this platform")
@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_unix_connection_is_allowed(method, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = "test.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(path)
        server.listen()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            result = getattr(client, method)(path)
            assert result in (None, 0)
            connection, _ = server.accept()
            connection.close()
