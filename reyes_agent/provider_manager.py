"""Persistent, truthful model-provider configuration and validation state.

Having an API key means CONFIGURED, not ONLINE.  A provider becomes ONLINE
only after a real bounded validation request or a successful model turn.  The
store contains a one-way credential fingerprint and operational metadata; it
never stores an API key, token, prompt, or response.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any

from reyes_agent import config
from reyes_agent import failures
from reyes_agent.memory.privacy import redact

NOT_CONFIGURED = "NOT_CONFIGURED"
CONFIGURED = "CONFIGURED"
VALIDATING = "VALIDATING"
ONLINE = "ONLINE"
RATE_LIMITED = "RATE_LIMITED"
FAILED = "FAILED"
DISABLED = "DISABLED"
STATES = {
    NOT_CONFIGURED, CONFIGURED, VALIDATING, ONLINE, RATE_LIMITED, FAILED, DISABLED,
}

_PROVIDERS = ("anthropic", "openai", "xai", "gemini", "ollama")
_DB_PATH = config.VAULT_PATH / "07-System" / "providers" / (
    "test-health.sqlite3" if config.ZENO_ENV == "test" else "health.sqlite3"
)
_SCHEMA_VERSION = 1
_DEFAULT_TIMEOUT_S = 8.0
_lock = threading.RLock()


def _credentials() -> dict[str, str]:
    return {
        "anthropic": config.ANTHROPIC_API_KEY,
        "openai": config.OPENAI_API_KEY,
        "xai": config.XAI_API_KEY,
        "gemini": config.GEMINI_API_KEY,
        "ollama": "local-enabled" if (
            config.OLLAMA_ENABLED or config.MODEL_PROVIDER == "ollama"
        ) else "",
    }


def _fingerprint(secret: str) -> str:
    if not secret:
        return ""
    return hashlib.sha256(("zeno-provider-v1:" + secret).encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS provider_health (
               provider TEXT PRIMARY KEY,
               credential_fingerprint TEXT NOT NULL,
               state TEXT NOT NULL,
               checked_at REAL NOT NULL,
               validated_at REAL,
               latency_ms REAL,
               error_category TEXT NOT NULL DEFAULT '',
               detail TEXT NOT NULL DEFAULT ''
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_meta (
               key TEXT PRIMARY KEY,
               value TEXT NOT NULL
           )"""
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(_SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def _stored() -> dict[str, dict[str, Any]]:
    try:
        with _lock, closing(_connect()) as conn:
            rows = conn.execute("SELECT * FROM provider_health").fetchall()
        return {str(row["provider"]): dict(row) for row in rows}
    except sqlite3.Error:
        return {}


def _write(provider: str, state: str, *, latency_ms: float = 0.0,
           error_category: str = "", detail: str = "", validated: bool = False) -> None:
    if provider not in _PROVIDERS or state not in STATES:
        return
    secret = _credentials().get(provider, "")
    if not secret:
        return
    now = time.time()
    safe_detail = redact(detail, limit=240)
    with _lock, closing(_connect()) as conn:
        previous = conn.execute(
            "SELECT validated_at FROM provider_health WHERE provider = ?", (provider,)
        ).fetchone()
        validated_at = now if validated else (
            float(previous["validated_at"]) if previous and previous["validated_at"] else None
        )
        conn.execute(
            """INSERT INTO provider_health(
                   provider, credential_fingerprint, state, checked_at,
                   validated_at, latency_ms, error_category, detail
               ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider) DO UPDATE SET
                   credential_fingerprint=excluded.credential_fingerprint,
                   state=excluded.state,
                   checked_at=excluded.checked_at,
                   validated_at=excluded.validated_at,
                   latency_ms=excluded.latency_ms,
                   error_category=excluded.error_category,
                   detail=excluded.detail""",
            (provider, _fingerprint(secret), state, now, validated_at,
             round(max(0.0, latency_ms), 2), error_category[:64], safe_detail),
        )
        conn.commit()


def _classify_error(message: str, status_code: int = 0) -> tuple[str, str]:
    category = failures.classify(message, status_code=status_code)
    return (RATE_LIMITED if category == failures.PROVIDER_RATE_LIMIT else FAILED), category


def record_runtime_result(provider: str, *, ok: bool, latency_s: float,
                          error: str = "") -> None:
    """Record a real SDK call, not a synthetic test/health assumption."""
    if provider not in _PROVIDERS or not _credentials().get(provider):
        return
    if ok:
        _write(provider, ONLINE, latency_ms=latency_s * 1000,
               detail="A real model request completed.", validated=True)
        return
    state, category = _classify_error(error)
    _write(provider, state, latency_ms=latency_s * 1000,
           error_category=category, detail=error, validated=False)


def _request_spec(provider: str) -> tuple[str, dict[str, str], str]:
    creds = _credentials()
    if provider == "anthropic":
        return (
            "https://api.anthropic.com/v1/models?limit=1",
            {"x-api-key": creds[provider], "anthropic-version": "2023-06-01"},
            "data",
        )
    if provider == "openai":
        base = config.OPENAI_BASE_URL or "https://api.openai.com/v1"
        return (base.rstrip("/") + "/models",
                {"Authorization": f"Bearer {creds[provider]}"}, "data")
    if provider == "xai":
        return ("https://api.x.ai/v1/models",
                {"Authorization": f"Bearer {creds[provider]}"}, "data")
    if provider == "gemini":
        return (
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
            {"x-goog-api-key": creds[provider]}, "models",
        )
    if provider == "ollama":
        base = config.OLLAMA_BASE_URL.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return (base.rstrip("/") + "/api/tags", {}, "models")
    raise ValueError(f"Unknown provider '{provider}'.")


def validate(provider: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Perform a real, bounded provider authentication/availability probe."""
    provider = str(provider or "").strip().lower()
    if provider not in _PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'.")
    secret = _credentials().get(provider, "")
    if not secret:
        return _public_row(provider, DISABLED if provider == "ollama" else NOT_CONFIGURED)

    _write(provider, VALIDATING, detail="Validation request in progress.")
    started = time.perf_counter()
    try:
        url, headers, expected_key = _request_spec(provider)
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "ZENO/1", **headers},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=max(1.0, min(20.0, timeout_s))) as response:
            status_code = int(getattr(response, "status", 200))
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
        if status_code != 200 or not isinstance(payload, dict) or expected_key not in payload:
            raise RuntimeError("Provider returned an unexpected validation response.")
        latency_ms = (time.perf_counter() - started) * 1000
        _write(provider, ONLINE, latency_ms=latency_ms,
               detail="Credentials and provider endpoint validated.", validated=True)
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            body = exc.read(65_536).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        error_text = f"{exc} {body}"
        state, category = _classify_error(error_text, int(exc.code))
        _write(provider, state, latency_ms=latency_ms, error_category=category,
               detail=f"HTTP {exc.code}: {redact(body, limit=180) or 'validation failed.'}")
    except Exception as exc:  # noqa: BLE001 -- validation returns typed state
        latency_ms = (time.perf_counter() - started) * 1000
        state, category = _classify_error(f"{type(exc).__name__}: {exc}")
        _write(provider, state, latency_ms=latency_ms, error_category=category,
               detail=f"{type(exc).__name__}: {exc}")
    return status()["providers"][provider]


def _public_row(provider: str, state: str, row: dict[str, Any] | None = None) -> dict[str, Any]:
    row = row or {}
    return {
        "provider": provider,
        "configured": state not in {NOT_CONFIGURED, DISABLED},
        "state": state,
        "checked_at": row.get("checked_at"),
        "validated_at": row.get("validated_at"),
        "latency_ms": row.get("latency_ms"),
        "error_category": row.get("error_category", ""),
        "detail": row.get("detail", "") if row else (
            "Local provider is disabled." if state == DISABLED else "No credential is configured."
        ),
    }


def status() -> dict[str, Any]:
    creds = _credentials()
    saved = _stored()
    providers: dict[str, dict[str, Any]] = {}
    for provider in _PROVIDERS:
        secret = creds.get(provider, "")
        if not secret:
            state = DISABLED if provider == "ollama" else NOT_CONFIGURED
            providers[provider] = _public_row(provider, state)
            continue
        row = saved.get(provider)
        if not row or row.get("credential_fingerprint") != _fingerprint(secret):
            providers[provider] = _public_row(provider, CONFIGURED, {
                "detail": "Credential is present but has not been validated.",
            })
            continue
        state = str(row.get("state") or CONFIGURED)
        providers[provider] = _public_row(
            provider, state if state in STATES else CONFIGURED, row
        )

    states = [item["state"] for item in providers.values()]
    if ONLINE in states:
        overall = ONLINE
    elif any(state in {FAILED, RATE_LIMITED} for state in states):
        overall = FAILED
    elif any(state in {CONFIGURED, VALIDATING} for state in states):
        overall = CONFIGURED
    else:
        overall = NOT_CONFIGURED
    return {
        "state": overall,
        "providers": providers,
        "online_count": sum(1 for state in states if state == ONLINE),
        "configured_count": sum(1 for state in states if state not in {NOT_CONFIGURED, DISABLED}),
        "database": str(_DB_PATH),
        "schema_version": _SCHEMA_VERSION,
        "truth_rule": "A key is CONFIGURED; only a real validation or model call is ONLINE.",
    }


def reset_validation(provider: str = "") -> None:
    """Explicit recovery/test hook. Credentials are never changed here."""
    with _lock, closing(_connect()) as conn:
        if provider:
            conn.execute("DELETE FROM provider_health WHERE provider = ?", (provider,))
        else:
            conn.execute("DELETE FROM provider_health")
        conn.commit()
