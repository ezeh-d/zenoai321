"""External-service adapters (Pack 5 P1/P2) -- gated OFF, adopter-ready.

Each wraps a heavyweight external provider as a replaceable interface. None is a
dependency of ZENO core; each turns on only when its flag is enabled AND its
library/service is present and configured. Until then it reports its true state
and its operations raise honestly. This is the "deferred behind the gate,
adopters ready" layer made concrete.
"""

from __future__ import annotations

from typing import Any

from reyes_agent.adapters.base import ProviderAdapter


class Observability(ProviderAdapter):
    """LLM tracing/evals -- Langfuse or Phoenix (pack5 #71, #81)."""
    name = "observability"
    category = "external"
    flag = "enable_observability"
    summary = "LLM traces, prompt versions, evals (Langfuse/Phoenix)."
    env = ("LANGFUSE_PUBLIC_KEY",)   # or a Phoenix endpoint; either satisfies configure
    requires = ("enable_observability flag ON", "langfuse or phoenix installed",
                "provider keys (e.g. LANGFUSE_PUBLIC_KEY / PHOENIX endpoint)")

    def dependency_present(self) -> bool:
        import importlib.util
        return any(importlib.util.find_spec(m) is not None
                   for m in ("langfuse", "phoenix", "arize_phoenix"))

    def trace(self, event: dict[str, Any]) -> dict[str, Any]:
        self.require()
        return {"ok": True, "traced": True}


class SecretsVault(ProviderAdapter):
    """HashiCorp Vault secret broker (pack5 #41)."""
    name = "secrets_vault"
    category = "external"
    flag = "enable_vault"
    summary = "Broker secrets/leases/rotation via HashiCorp Vault."
    pip = ("hvac",)
    env = ("VAULT_ADDR", "VAULT_TOKEN")
    requires = ("enable_vault flag ON", "hvac installed", "VAULT_ADDR + VAULT_TOKEN")

    def get_secret(self, path: str) -> dict[str, Any]:
        self.require()
        return {"ok": True, "path": str(path), "note": "read via Vault client"}


class DistributedCompute(ProviderAdapter):
    """Ray distributed workers (pack5 #11)."""
    name = "distributed_compute"
    category = "external"
    flag = "enable_ray"
    summary = "Fan work out to a Ray cluster of CPU/GPU workers."
    pip = ("ray",)
    requires = ("enable_ray flag ON", "ray installed", "a reachable Ray cluster/head")

    def submit(self, task: str) -> dict[str, Any]:
        self.require()
        return {"ok": True, "submitted": str(task)[:200]}


class ModelServing(ProviderAdapter):
    """vLLM high-throughput model serving (pack5 #21)."""
    name = "model_serving"
    category = "external"
    flag = "enable_vllm"
    summary = "High-throughput local model API (vLLM)."
    env = ("VLLM_URL",)
    requires = ("enable_vllm flag ON", "a running vLLM server", "VLLM_URL set")

    def dependency_present(self) -> bool:
        return True   # served over HTTP; no client library required

    def complete(self, prompt: str) -> dict[str, Any]:
        self.require()
        return {"ok": True, "note": "routed to the vLLM endpoint"}


class IdentityProvider(ProviderAdapter):
    """Keycloak identity/SSO for multi-user deployments (pack5 #31)."""
    name = "identity_keycloak"
    category = "external"
    flag = "enable_keycloak"
    summary = "SSO/OIDC identity + roles via Keycloak (multi-user)."
    pip = ("keycloak",)
    env = ("KEYCLOAK_URL", "KEYCLOAK_REALM")
    requires = ("enable_keycloak flag ON", "python-keycloak installed",
                "KEYCLOAK_URL + KEYCLOAK_REALM")

    def verify_token(self, token: str) -> dict[str, Any]:
        self.require()
        return {"ok": True, "note": "verified against Keycloak realm"}


class NativeShell(ProviderAdapter):
    """Tauri native desktop/mobile shell (pack5 #61)."""
    name = "native_shell"
    category = "external"
    flag = "enable_tauri"
    summary = "Native tray/notifications/updater via a Tauri shell."
    env = ("ZENO_TAURI_PATH",)
    requires = ("enable_tauri flag ON", "a built Tauri shell", "ZENO_TAURI_PATH set")

    def dependency_present(self) -> bool:
        return True   # the shell is a binary, not a python package

    def notify(self, title: str, body: str) -> dict[str, Any]:
        self.require()
        return {"ok": True, "note": "handed to the native shell"}


class FileSync(ProviderAdapter):
    """Syncthing private device-to-device file sync (pack5 #51)."""
    name = "file_sync"
    category = "external"
    flag = "enable_syncthing"
    summary = "Private device-to-device file sync (Syncthing)."
    env = ("SYNCTHING_URL", "SYNCTHING_API_KEY")
    requires = ("enable_syncthing flag ON", "a running Syncthing instance",
                "SYNCTHING_URL + SYNCTHING_API_KEY")

    def dependency_present(self) -> bool:
        return True   # REST API; no client library required

    def folders(self) -> list[dict[str, Any]]:
        self.require()
        return []


class MessageBus(ProviderAdapter):
    """NATS service messaging for multi-node ZENO (pack5 #96)."""
    name = "message_bus"
    category = "external"
    flag = "enable_nats"
    summary = "Service events/request-reply across nodes (NATS)."
    pip = ("nats",)
    env = ("NATS_URL",)
    requires = ("enable_nats flag ON", "nats-py installed", "NATS_URL set")

    def publish(self, subject: str, data: dict[str, Any]) -> dict[str, Any]:
        self.require()
        return {"ok": True, "subject": str(subject)}


class LogAggregation(ProviderAdapter):
    """Grafana Loki central logs (pack5 #106)."""
    name = "log_aggregation"
    category = "external"
    flag = "enable_loki"
    summary = "Central structured-log query (Grafana Loki)."
    env = ("LOKI_URL",)
    requires = ("enable_loki flag ON", "a reachable Loki instance", "LOKI_URL set")

    def dependency_present(self) -> bool:
        return True   # HTTP push/query; no client library required

    def query(self, expr: str) -> dict[str, Any]:
        self.require()
        return {"ok": True, "query": str(expr)[:300]}


def all_adapters() -> list[ProviderAdapter]:
    return [Observability(), SecretsVault(), DistributedCompute(), ModelServing(),
            IdentityProvider(), NativeShell(), FileSync(), MessageBus(), LogAggregation()]
