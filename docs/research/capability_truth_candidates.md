# Capability truth and registry candidates

## Evaluated

- [Official MCP Registry](https://github.com/modelcontextprotocol/registry):
  official discovery metadata and a frozen v0.1 API, but still a registry of
  declarations rather than runtime proof. Selected only as an optional discovery
  source behind ZENO's allowlist; never an auto-installer.
- [A2A 1.0 specification](https://a2a-protocol.org/latest/specification/): Agent
  Cards provide identity, interfaces, skills, security requirements and signed
  metadata. Selected as the remote-agent metadata contract; ZENO's existing
  `a2a_registry.py` remains the trust boundary.
- [agentoperations/agent-registry](https://github.com/agentoperations/agent-registry):
  useful promotion/evaluation/provenance concepts, but a young standalone Go
  registry would duplicate local authorities. Rejected for deployment; lifecycle
  concepts were already implemented locally.

## Chosen design

`GlobalToolRegistry` remains authoritative for executable local tools.
`CapabilityTruthEngine` joins declaration, installation, authentication, device,
health, dependencies, reputation and verification. MCP/A2A metadata can enrich
it, but can never mark a capability proven by itself.
