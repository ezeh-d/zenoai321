# ZENO self-extension and GitHub integration

ZENO can accept an owner-supplied GitHub repository/file/directory/release URL,
local file/directory/archive, Python or Node package reference, MCP server,
plugin, or skill reference and perform a bounded review. Acquisition is
read-only: it does not clone, install, extract, import, or execute source.

## Lifecycle and authorities

`SelfExtensionEngine` coordinates the existing `CapabilityTruth`,
`GlobalToolRegistry`, feature flags, sandbox manager, Mission Control, and the
atomic `extensions/catalog.json` registry. It does not create another tool
executor or permission engine.

The enforced lifecycle is `DISCOVERED → INSPECTING → SECURITY_REVIEW →
COMPATIBILITY_REVIEW → SANDBOX_TEST → BENCHMARK → APPROVAL → CANARY → ACTIVE`.
Terminal and recovery states are `REJECTED`, `QUARANTINED`, `BROKEN`,
`DISABLED`, and `REMOVED`. Invalid state jumps are refused.

Static review covers bounded source structure, language and manifests,
entrypoints, dependencies and lockfiles, install scripts, permissions,
network endpoints, subprocess/filesystem/browser/device markers, embedded
secrets, license implications, Windows/runtime compatibility, useful
components, and overlap with existing ZENO tools. A measurable trust heuristic
is recorded, but is explicitly not proof of safety. A live dependency-advisory
provider is not configured, so that field reports
`NOT_RUN_NO_ADVISORY_PROVIDER` instead of inventing a result.

## Execution and promotion rules

- Executable source is never run by the importer or static inspector.
- Archive members are read in memory with file/total limits; traversal paths
  are rejected and archives are never extracted.
- GitHub requests are HTTPS GETs restricted to `api.github.com` and bounded in
  response/file/count size.
- Unknown executable code requires AIO Sandbox or E2B. The existing local
  restricted worker is not treated as an OS security boundary.
- Generated adapters are declarative manifests marked
  `PLANNED_NOT_EXECUTABLE`; generation cannot fake an implementation.
- Owner approval without a real adapter health check does not activate it.
- A healthy universal-tool adapter enters a 10% feature-flag canary. It becomes
  `ACTIVE` only after recorded verification evidence; failed canaries are
  disabled and unregistered.
- Only a successfully tested adapter is registered with the existing
  `GlobalToolRegistry` and declared tested to `CapabilityTruth`.
- Updates are detected but never blindly applied. They repeat inspection,
  sandbox, regression, benchmark and canary.
- Disable/remove unregisters the external adapter and disables its feature
  flag. Native tools cannot be unregistered by this subsystem.

Prohibited-purpose sources—including credential theft, phishing, malware,
covert surveillance, unauthorized persistence or remote access, and
indiscriminate disruption—are rejected, not converted into runnable ZENO
capabilities.

## Owner tools and visibility

The owner tools are `extension_inspect`, `extension_status`,
`extension_search` (candidate metadata only), `extension_update_check`, and the
confirmation-gated `extension_approve`, `extension_rollback`, and
`extension_remove`. TOSIN receives these tools for repository work. Mission
Control has a lazy `EXTENSIONS` section; ZenoDoctor accepts an `ext_…`
identifier.

## Current deployment limit

This workstation does not currently have a configured strong AIO/E2B runner.
Therefore real executable GitHub/package code correctly stops in
`QUARANTINED / NOT_EXECUTED`. This is an environmental security gate, not an
unfinished-success claim. A live inspection of Click's `src/click/core.py`
read 147,845 bytes at pinned commit
`2c8cd3ac958a7eb316d67f2d316c27086c4c0369`, passed static syntax, and remained
quarantined because no strong sandbox execution evidence existed.
