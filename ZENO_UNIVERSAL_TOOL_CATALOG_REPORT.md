# ZENO Universal Tool Catalog — Stable Integration Report

Initial adapter pass: 2026-08-21

Universal registry/UI completion: 2026-08-24

## Interpretation

The master catalog is a capability and research specification, not a safe
instruction to clone every named repository. Its own operating rules require
selective adapters, one provider per capability, feature flags, bounded
workers, permission checks, verification and rollback. This pass therefore
installed every confirmed lightweight dependency for which the current ZENO
codebase has a maintained adapter, while preserving heavy or duplicative
providers as lazy optional integrations.

## Existing Architecture Reused

ZENO already has the catalog's core architecture rather than needing another
competing runtime:

- one tool registry with 299 registered tools and only 12 core schemas sent to
  the model by default;
- a detected capability registry that distinguishes presence, configuration,
  authorization and availability;
- a bounded Kernel/task runtime, workflow engine, Event Bus, permission engine,
  verification/recovery layers and device manager;
- lazy Playwright/browser, voice, wake word, vision, MCP, memory, agent and
  Phase 3 integration managers;
- allow-listed MCP discovery with no automatic third-party server install;
- DuckDB and sqlite-vec as the existing bounded data/vector engines;
- Living Memory as the canonical local memory layer, with Mem0 optional and
  disabled unless deliberately configured.

Creating parallel registries, schedulers, vector databases, agent frameworks
or background listeners would have reduced reliability, so none were added.

## Universal Registry and Capability Library

Every executable tool is now projected through one normalized `ToolAdapter`
contract: versioned metadata, input/output schema, permissions, supported
devices, health, validation, managed execution, bounded timeout and cooperative
cancellation. The adapter never calls a function directly; it delegates to the
existing `reyes_agent.tools.run_tool` authority, so specialist scopes,
permissions, confirmations, confidence rules, verification, audit events and
recovery remain enforced in one place.

`GlobalToolRegistry` implements the catalog operations `get`,
`find_by_capability`, `find_by_device`, `health`, `list_available`,
`list_degraded` and `resolve_best_tool`. Resolution considers health,
permission, device, recent reputation/latency, confirmation cost and local
privacy. A normal read return is reported as `RETURNED_UNVERIFIED`, not falsely
promoted to proof of an external side effect.

The complete 148-section catalog and 57 provider candidates are available
through three lazy read-only tools, loopback-only API routes and the dashboard's
new **Tool Library** command. The panel fetches only while open, performs no
polling, cancels stale searches and releases its DOM rows when closed. Provider
state distinguishes installed adapters, experimental disabled alternatives and
owner-account requirements without returning credential values.

## Newly Installed and Integrated

| Capability | Installed package | Real ZENO path | Runtime behavior |
|---|---|---|---|
| Native Windows UIA | pywinauto 0.6.9 | `computer/windows/pywinauto_backend.py` | Feature-flagged, imported only on use |
| PDF text | PyMuPDF 1.28.2 | `ocr.extract_document_text` | Bounded to 50 MiB, 500 pages and caller character cap |
| Word text | python-docx 1.2.0 | `ocr.extract_document_text` | Bounded paragraphs/table rows; no startup import |
| Excel text | openpyxl 3.1.5 | `ocr.extract_document_text` | Read-only/data-only, bounded sheets/rows/cells |
| PowerPoint text | python-pptx 1.0.2 | `ocr.extract_document_text` | Bounded slides/shapes; no startup import |

The capability registry now reports `pywinauto` and `native_documents` from
real dependency probes. The OCR/document API reports the actual engine used
and never claims OCR confidence for deterministic structural extraction.

## Installer and Diagnostic Repairs

- `install.py` now uses real argument parsing. `--help` exits without changing
  the environment and unknown arguments fail instead of silently starting an
  install.
- Compatible packages are no longer upgraded implicitly. Upgrades require the
  explicit `--upgrade` switch; pip itself requires `--upgrade-pip`.
- `--catalog-safe` installs only supported lightweight adapters.
- `--dry-run`, `--skip-browser-download` and `--skip-doctor` are explicit and
  tested.
- Every installation ends with the read-only doctor and `pip check` unless
  explicitly skipped.
- The doctor no longer crashes on a Windows CP1252 terminal and now reports
  native OCR, pywinauto and all four document readers.

## Live Verification

- Dependency consistency: `pip check` passed with no broken requirements.
- Native document suite generated and reread real PDF, DOCX, XLSX and PPTX
  fixtures; size and character bounds were exercised.
- Playwright launched Chromium headlessly, rendered a real DOM and verified
  title, text and state through selectors.
- pywinauto queried the real Windows UIA desktop and observed 11 visible
  top-level windows; the adapter remained unloaded while its feature flag was
  off and accurately reported loaded state after activation.
- ffmpeg 8.1.2 executed successfully.
- Ollama executed successfully and reported the installed local models.
- Cold tool/runtime measurement: 299 registered tools, 12 default provider
  schemas, 950.6 ms import, 17.38 MiB process-memory delta and one thread before
  and after import. A cold catalog status took 69.8 ms and normalized registry
  health took 164.8 ms. No worker, provider process or polling loop was created
  by inventory/registry inspection.
- Detected capability state after installation: 26 of 32 high-level
  capabilities READY. The remaining six are reported honestly below.
- Focused registry/catalog/router/adapter regression: 72 tests passed after
  the final natural-language route was connected; the wider adjacent
  integration pass completed 121 tests without failure.
- Complete maintained ZENO regression after the universal contract and UI
  completion: 1,750 tests passed in 569.20 seconds with deprecation warnings
  promoted to errors. The desktop web shell uses FastAPI's supported
  lifespan API. Under an earlier deliberately strict loaded run, transient
  Windows process pressure exposed MCP discovery and trusted-sandbox timeout
  edges; read-only discovery now retries exactly once, effectful MCP calls are
  never replayed, and trusted local execution has a still-bounded 45-second
  default. A live-network test also now ignores stale addresses from adapters
  Windows reports down instead of asking production to trust an inactive
  subnet.

## Deliberately Not Auto-Installed

| Item | Reason |
|---|---|
| Docling/Torch/transformer document stack | The bounded native readers now cover the current formats without multi-GB model dependencies; Docling remains a lazy feature flag |
| pandas | No current ZENO adapter requires it; DuckDB is the existing bounded analytics authority |
| extra vector databases | sqlite-vec and DuckDB already provide the local authority; duplicate stores create drift and memory cost |
| extra agent/orchestration frameworks | ZENO Kernel, Mission Engine, Council and workflow runtime are already authoritative |
| Tesseract | Windows OCR is installed and working; adding a second native OCR binary would duplicate capability |
| Silero/Torch VAD | The current lightweight VAD/wake pipeline avoids the heavyweight Torch runtime at idle |
| every GitHub/MCP catalog entry | Untrusted servers are never auto-installed; the MCP allowlist remains the security boundary |
| Gmail/calendar/Home Assistant/GitHub activation | These require owner-selected accounts, scopes or credentials; packages cannot create legitimate authorization |
| cloud/provider alternatives with no adapter | A package import is not a working capability; providers need a tested adapter, health check and fallback first |

Current non-ready states are truthful rather than simulated: GitHub and Home
Assistant require owner credentials; email and calendar require an owner-linked
account; Docling and pandas are optional dependency alternatives. None blocks
the installed ZENO core.

The Tool Library provider matrix currently contains 33 installed adapters, 22
experimental/disabled alternatives and two owner-login integrations. This is
an installation/integration view, not a claim that physical hardware, external
accounts or every live endpoint was exercised during this pass.

## Stability Rules Preserved

- no unlimited workers, extra startup service, polling loop or animation loop;
- no provider or browser preload added;
- no secret, account or API credential created or exposed;
- no arbitrary package installer or MCP auto-discovery path;
- all new readers are local, lazy, size-bounded and error-isolated;
- legacy `.doc`/`.xls` files are reported as requiring conversion rather than
  being falsely treated as modern Office files.

## Remaining Physical/Account Validation

Camera, microphone, external accounts, real mobile devices and consequential
desktop actions require owner hardware/permission/account evidence. They were
not invoked merely to make a catalog line appear green. ZENO continues to use
the existing permission and verification pipeline when those capabilities are
requested.

Live UI verification used an isolated local static harness so it did not start
a second ZENO runtime: the command palette opened Tool Library, all 205 rows
(148 sections + 57 providers) rendered, the browser filter returned four real
matches, close hid the panel and retained zero cards. Physical-account/provider
tests remain intentionally separate because a package cannot grant login,
device presence, paid quota or consequential-action consent.
