"""Service-specific HTTP broker and Agent Vault adapter.

The caller receives a redacted receipt, never a credential.  When Agent
Vault is configured, callers receive only its placeholder/proxy contract.
Without Agent Vault the trusted broker can attach a key internally for a
strictly allowlisted HTTPS endpoint.
"""
from __future__ import annotations

import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import requests

from reyes_agent import audit
from reyes_agent.security.capabilities import authorize_service
from reyes_agent.security.credentials.service_rules import rule_for
from reyes_agent.security.secrets import manager as secrets


@dataclass(frozen=True)
class BrokerReceipt:
    ok: bool
    state: str
    agent: str
    service: str
    endpoint_category: str
    status_code: int | None
    duration_ms: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class CredentialBroker:
    def _agent_vault(self) -> dict[str, Any]:
        address = os.environ.get("AGENT_VAULT_ADDR", "").strip()
        vault = os.environ.get("AGENT_VAULT_VAULT", "").strip()
        token_set = secrets.source_of("AGENT_VAULT_TOKEN").found
        if not address or not vault or not token_set:
            return {"state": "NOT_CONFIGURED", "configured": False}
        parsed = urllib.parse.urlparse(address)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return {"state": "FAILED", "configured": True, "reason": "invalid Agent Vault address"}
        return {"state": "STANDBY", "configured": True, "address": address,
                "vault": vault, "strict_egress": True}

    def status(self) -> dict[str, Any]:
        vault = self._agent_vault()
        return {
            "state": "WORKING" if secrets.describe().get("os_credential_store") else "DEGRADED",
            "local_secret_store": secrets.describe().get("backend"),
            "agent_vault": vault,
            "raw_secrets_to_agents": False,
            "default_unmatched_host_policy": "deny",
        }

    def request(self, agent: str, service: str, method: str, url: str, *,
                json_body: dict[str, Any] | None = None, timeout_s: float = 10.0,
                confirmed: bool = False) -> tuple[BrokerReceipt, Any]:
        started = time.perf_counter()
        rule = rule_for(service)
        parsed = urllib.parse.urlparse(url)
        endpoint = f"{parsed.hostname or 'invalid'}:{parsed.path[:80]}"
        scope_ok, scope_reason, scoped_agent = authorize_service(service)
        actor = str(agent or scoped_agent or "unknown").casefold()

        def receipt(ok: bool, state: str, reason: str, code: int | None = None) -> BrokerReceipt:
            value = BrokerReceipt(ok, state, actor, str(service).casefold(), endpoint, code,
                                  int((time.perf_counter() - started) * 1000), reason)
            audit.log("credential_broker", actor=actor, action=f"{service}:{method.upper()}",
                      policy="service_egress_allowlist", outcome="completed" if ok else "blocked",
                      endpoint_category=endpoint, status_code=code, duration_ms=value.duration_ms,
                      reason=reason)
            return value

        if not scope_ok:
            return receipt(False, "DENIED", scope_reason), None
        if rule is None:
            return receipt(False, "DENIED", "service has no broker rule"), None
        if parsed.scheme != "https" or not parsed.hostname:
            return receipt(False, "DENIED", "broker requires a valid HTTPS endpoint"), None
        allowed_hosts = set(rule.hosts)
        if service == "gotify":
            configured = urllib.parse.urlparse(os.environ.get("ZENO_GOTIFY_URL", "")).hostname
            if configured:
                allowed_hosts.add(configured.casefold())
        if parsed.hostname.casefold() not in {host.casefold() for host in allowed_hosts}:
            return receipt(False, "DENIED", "endpoint is outside the service egress allowlist"), None
        if method.upper() not in {"GET", "HEAD"} and rule.write_requires_confirmation and not confirmed:
            return receipt(False, "APPROVAL_REQUIRED", "write operation requires owner confirmation"), None
        secret = secrets.get(rule.secret_key)
        if not secret:
            return receipt(False, "AUTH_REQUIRED", f"{rule.secret_key} is not configured"), None
        headers = {"Accept": "application/json", "User-Agent": "ZENO-Credential-Broker/1"}
        if rule.auth_scheme == "bearer":
            headers["Authorization"] = f"Bearer {secret}"
        else:
            headers["X-Gotify-Key"] = secret
        try:
            response = requests.request(method.upper(), url, headers=headers, json=json_body,
                                        timeout=max(1.0, min(float(timeout_s), 30.0)))
            try:
                payload = response.json()
            except ValueError:
                payload = {"body_length": len(response.content)}
            ok = 200 <= response.status_code < 300
            return receipt(ok, "COMPLETED" if ok else "FAILED",
                           "provider confirmed request" if ok else "provider rejected request",
                           response.status_code), payload
        except requests.RequestException as exc:
            return receipt(False, "OFFLINE", type(exc).__name__), None


_BROKER = CredentialBroker()


def get_broker() -> CredentialBroker:
    return _BROKER
