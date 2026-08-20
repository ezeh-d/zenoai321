"""Regression evidence for the Codex evolution stability pass."""

from __future__ import annotations

import concurrent.futures
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time


def _answer(address: str, port: int = 443) -> tuple:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr


def test_research_target_rejects_every_non_global_dns_answer(monkeypatch) -> None:
    from reyes_agent.research.crawler import limits

    answers = {
        "private.example": [_answer("172.20.1.4")],
        "carrier.example": [_answer("100.64.1.4")],
        "integer.example": [_answer("127.0.0.1")],
        "mixed.example": [_answer("93.184.216.34"), _answer("10.0.0.8")],
        "public.example": [_answer("93.184.216.34")],
    }
    monkeypatch.setattr(limits.socket, "getaddrinfo",
                        lambda host, port, **_: answers[host])
    monkeypatch.setattr(limits, "robots_allows", lambda _url: (True, "test"))

    for host in ("private.example", "carrier.example", "integer.example", "mixed.example"):
        ok, why = limits.may_fetch(f"https://{host}/page", limits.Budget())
        assert ok is False
        assert "private" in why or "non-global" in why

    assert limits.may_fetch("https://public.example/page", limits.Budget())[0] is True


def test_research_rejects_credentials_and_non_web_ports(monkeypatch) -> None:
    from reyes_agent.research.crawler import limits

    monkeypatch.setattr(limits.socket, "getaddrinfo",
                        lambda host, port, **_: [_answer("93.184.216.34", port)])
    for url in ("https://user:password@example.com/page",
                "https://example.com:8765/page"):
        ok, _why = limits.may_fetch(url, limits.Budget())
        assert ok is False


class _Response:
    def __init__(self, status: int, chunks: list[bytes]) -> None:
        self.status_code = status
        self.headers = {"content-type": "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self._chunks = chunks
        self.closed = False

    def iter_content(self, _size: int):
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


def test_streamed_research_response_is_closed_and_redirects_are_not_followed(monkeypatch) -> None:
    import requests

    from reyes_agent.research.crawler import limits, manager

    redirect = _Response(302, [b"must not be read"])
    seen: dict[str, object] = {}

    def fake_get(_url: str, **kwargs):
        seen.update(kwargs)
        return redirect

    monkeypatch.setattr(limits, "may_fetch", lambda *_args, **_kwargs: (True, "test"))
    monkeypatch.setattr(limits, "wait_for_host", lambda _url: None)
    monkeypatch.setattr(requests, "get", fake_get)
    result = manager.fetch("https://public.example/start", limits.Budget())

    assert result.error.startswith("redirect refused")
    assert seen["allow_redirects"] is False
    assert redirect.closed is True


def test_robots_fetch_is_bounded_closed_and_never_follows_redirects(monkeypatch) -> None:
    import requests

    from reyes_agent.research.crawler import limits

    response = _Response(302, [b"redirect body"])
    seen: dict[str, object] = {}

    def fake_get(_url: str, **kwargs):
        seen.update(kwargs)
        return response

    limits._robots_cache.clear()
    monkeypatch.setattr(requests, "get", fake_get)
    allowed, why = limits.robots_allows("https://public.example/page")
    assert allowed is True and "no robots" in why
    assert seen["allow_redirects"] is False
    assert response.closed is True


def test_streamed_research_enforces_the_exact_byte_cap(monkeypatch) -> None:
    import requests

    from reyes_agent.research.crawler import limits, manager

    response = _Response(200, [b"a" * (limits.MAX_BYTES_PER_PAGE + 65_536)])
    observed: dict[str, int] = {}
    monkeypatch.setattr(limits, "may_fetch", lambda *_args, **_kwargs: (True, "test"))
    monkeypatch.setattr(limits, "wait_for_host", lambda _url: None)
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: response)
    monkeypatch.setattr(manager, "to_text", lambda markup: (
        observed.setdefault("bytes", len(markup)) and "title", markup, []))

    manager.fetch("https://public.example/page", limits.Budget())
    assert observed["bytes"] == limits.MAX_BYTES_PER_PAGE
    assert response.closed is True


def test_provider_clients_are_initialized_once_under_concurrency(monkeypatch) -> None:
    from reyes_agent import provider

    calls = 0
    lock = threading.Lock()

    class SDK:
        @staticmethod
        def OpenAI(**_kwargs):
            nonlocal calls
            with lock:
                calls += 1
            time.sleep(0.02)
            return object()

    monkeypatch.setattr(provider.config, "OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr(provider, "_openai_module", lambda: SDK())
    monkeypatch.setattr(provider, "_openai_client", None)
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        clients = list(pool.map(lambda _: provider._get_openai_client(), range(48)))

    assert calls == 1
    assert len({id(client) for client in clients}) == 1


def test_documented_piper_model_variable_is_the_authoritative_setting() -> None:
    """The router and direct TTS path must not read two different settings."""
    env = os.environ.copy()
    env["ZENO_PIPER_MODEL"] = "C:/models/primary.onnx"
    env["PIPER_MODEL"] = "C:/models/legacy.onnx"
    result = subprocess.run(
        [sys.executable, "-c",
         "from reyes_agent import config; print(config.PIPER_MODEL)"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert result.stdout.strip().endswith("C:/models/primary.onnx")


def test_concurrent_councils_share_one_bounded_executor(monkeypatch) -> None:
    from reyes_agent import council

    council.shutdown_executor()
    chosen = [council.Dossier(str(index), str(index), "test") for index in range(4)]
    worker_names: set[str] = set()
    lock = threading.Lock()

    monkeypatch.setattr(council, "load_dossiers",
                        lambda: ({item.advisor_id: item for item in chosen}, []))
    monkeypatch.setattr(council, "select_advisors", lambda *_args, **_kwargs: chosen)

    def advisor(item, _question, _context):
        with lock:
            worker_names.add(threading.current_thread().name)
        time.sleep(0.01)
        return {"advisor": item.advisor_id, "name": item.name, "opinion": "ok",
                "fabricated": [], "error": ""}

    monkeypatch.setattr(council, "_run_advisor", advisor)
    monkeypatch.setattr(council, "_run_skeptic", lambda *_args: "ok")
    monkeypatch.setattr(council, "_store", lambda *_args: None)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as callers:
            list(callers.map(lambda _: council.hold_meeting("test"), range(10)))
        assert len(worker_names) <= council._MAX_ADVISORS
        assert all(name.startswith("zeno-council") for name in worker_names)
    finally:
        council.shutdown_executor()
