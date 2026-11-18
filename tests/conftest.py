from __future__ import annotations

import importlib
import ipaddress
import socket

import pytest


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    for name in (
        "POD_CONFIG_PATH", "POD_TOPICS_PATH", "POD_GENERATED_DIR", "POD_PROMPTS_DIR",
        "POD_RESEARCH_PROMPT_PATH", "POD_SCRIPT_OVERVIEW_PROMPT_PATH", "POD_SCRIPT_DEEP_DIVE_PROMPT_PATH",
        "POD_HOST", "POD_PORT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_MODEL", "AZURE_SPEECH_KEY",
        "ELEVENLABS_API_KEY", "AZURE_STORAGE_CONNECTION_STRING",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(tmp_path / "runtime"))
    modules = [importlib.import_module(f"app.{name}") for name in (
        "config", "storage", "prompt_loader", "feedgen", "research", "script_writer",
        "tts_elevenlabs", "tts_azure_speech", "tts_dispatch", "azure_static_uploader", "publisher", "worker", "app",
    )]
    for module in modules:
        importlib.reload(module)


@pytest.fixture(autouse=True)
def network_guard(request, monkeypatch):
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    bind = socket.socket.bind
    integration = request.node.get_closest_marker("integration") is not None

    def check(address):
        if integration and isinstance(address, tuple):
            try:
                if ipaddress.ip_address(address[0]).is_loopback:
                    return
            except ValueError:
                pass
        raise AssertionError(f"Unexpected network access in test: {address!r}")

    def guarded_connect(sock, address):
        check(address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        check(address)
        return connect_ex(sock, address)

    def guarded_bind(sock, address):
        check(address)
        return bind(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket.socket, "bind", guarded_bind)
