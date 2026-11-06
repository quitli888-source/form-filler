"""Privacy regressions never use a live network or provider credential."""
import socket
import pytest


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("Unexpected network access in offline test suite")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
