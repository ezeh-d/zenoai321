"""Auditable egress allowlists for brokered services."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceRule:
    service: str
    hosts: frozenset[str]
    secret_key: str
    auth_scheme: str = "bearer"
    write_requires_confirmation: bool = True


RULES: dict[str, ServiceRule] = {
    "github": ServiceRule("github", frozenset({"api.github.com"}), "GITHUB_TOKEN"),
    "ntfy": ServiceRule("ntfy", frozenset({"ntfy.sh"}), "NTFY_TOKEN", write_requires_confirmation=False),
    "gotify": ServiceRule("gotify", frozenset(), "GOTIFY_TOKEN", auth_scheme="x-gotify-key", write_requires_confirmation=False),
    "infisical": ServiceRule("infisical", frozenset({"app.infisical.com"}), "INFISICAL_TOKEN"),
}


def rule_for(service: str) -> ServiceRule | None:
    return RULES.get(str(service or "").strip().casefold())
