"""Thin agent-facing entry points for lazy Phase 3 capabilities."""
from __future__ import annotations

import json
from pathlib import Path

from reyes_agent.tools import register


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


@register(name="phase3_status",
          description="Show real enabled, disabled and available states for ZENO advanced integrations without starting them.",
          input_schema={"type": "object", "properties": {}}, light=True)
def phase3_status() -> str:
    from reyes_agent.phase3 import status
    return _json(status())


@register(name="episodic_search",
          description="Search explicitly enabled local Screenpipe or ActivityWatch history; sensitive windows are excluded.",
          input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]})
def episodic_search(query: str, limit: int = 20) -> str:
    from reyes_agent.context.episodic import get_provider
    return _json(get_provider().query(query, limit=limit))


@register(name="read_document_structured",
          description="Parse a document into bounded retrievable chunks, using Docling when enabled and local OCR otherwise.",
          input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
def read_document_structured(path: str) -> str:
    from reyes_agent.knowledge.documents import DocumentLoader
    result = DocumentLoader().load(path)
    if len(result.get("chunks", [])) > 8:
        result["chunks"] = result["chunks"][:8]
        result["response_truncated"] = True
    return _json(result)


def _graph():
    from reyes_agent import config
    from reyes_agent.memory.graph import KnowledgeGraph
    return KnowledgeGraph(config.VAULT_PATH / "07-System" / "phase3_graph.sqlite3")


@register(name="knowledge_graph_query",
          description="Query current or historical temporal relationships in ZENO's bounded local knowledge graph.",
          input_schema={"type": "object", "properties": {"query": {"type": "string"}, "include_history": {"type": "boolean"}, "limit": {"type": "integer"}}})
def knowledge_graph_query(query: str = "", include_history: bool = False, limit: int = 30) -> str:
    return _json(_graph().query(query, include_history=include_history, limit=limit))


@register(name="knowledge_graph_remember",
          description="Store one meaningful sourced temporal relationship; deduplicates repeats and preserves contradictory history.",
          input_schema={"type": "object", "properties": {"subject": {"type": "string"}, "relationship": {"type": "string"}, "object": {"type": "string"}, "confidence": {"type": "number"}, "source": {"type": "string"}}, "required": ["subject", "relationship", "object"]})
def knowledge_graph_remember(subject: str, relationship: str, object: str,
                             confidence: float = 1.0, source: str = "owner") -> str:
    return _json(_graph().add(subject, relationship, object, confidence=confidence, source=source))


@register(name="engineering_backends",
          description="Inspect engineering-agent backends and select one within an allowed workspace; starts no external agent.",
          input_schema={"type": "object", "properties": {"workspace": {"type": "string"}, "preferred": {"type": "string"}}})
def engineering_backends(workspace: str = "", preferred: str = "") -> str:
    from reyes_agent.engineering import EngineeringManager
    return _json(EngineeringManager().select(Path(workspace) if workspace else None, preferred=preferred))


@register(name="mobile_device_status",
          description="Discover explicitly authorized Android devices without network pairing or public control endpoints.",
          input_schema={"type": "object", "properties": {}})
def mobile_device_status() -> str:
    from reyes_agent.devices.mobile import MobileDeviceManager
    return _json(MobileDeviceManager().discover())


@register(name="sandbox_status",
          description="Show where generated code would run and whether optional E2B is genuinely available.",
          input_schema={"type": "object", "properties": {}})
def sandbox_status() -> str:
    from reyes_agent.sandbox import SandboxManager
    return _json(SandboxManager.status())
