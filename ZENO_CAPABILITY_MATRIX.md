# ZENO Capability Matrix

Date: 2026-08-17

`DONE` means the native ZENO contract is implemented and tested. `READY WITH
LIMITATIONS` names a real external, hardware, or corpus constraint.

| Spec phase | Status | Evidence / limit |
|---|---|---|
| 1 Repository audit | DONE | architecture/security/static/test audit; concrete defects repaired |
| 2 Single core | DONE | singleton Kernel, registries, Event Bus, worker pool, lifecycle |
| 3 Conversation | READY WITH LIMITATIONS | streaming STT/TTS, barge-in, endpointing, Pidgin context; provider latency external |
| 4 Wake word | READY WITH LIMITATIONS | one local-capable engine/state machine; no custom consented ZENO model |
| 5 Brain/router | DONE | local route, scoped schemas, fallbacks, sessions/traces |
| 6 Council/Agent Space | DONE | real lifecycle events, lazy visuals, bounded delegation |
| 7 Windows super-agent | DONE | API/UIA/Win32/deterministic/visual ladder and postconditions |
| 8 Observe and repeat | DONE | explicit Teach Mode, review, approval, replay, verification |
| 9 Browser agent | DONE | persistent Playwright, timeouts/recovery/verification |
| 10 Execution engine | DONE | command policy, confinement, bounded processes, audit |
| 11 Vision | READY WITH LIMITATIONS | screen/OCR/grounding; optional heavy models lazy/not installed |
| 12 Memory/Digital DNA | DONE | session/durable/semantic/workflow/preference/agent policy; optional Mem0 |
| 13 Learning | DONE | approved skills, demonstrations, corrections, versioning, trust checks |
| 14 Opportunity Engine | DONE | evidence model, nine-factor score, persistence, lazy adapters |
| 15 Market learning | DONE | dated typed observations and expiry; no background scraping |
| 16 Builder Mode | READY WITH LIMITATIONS | real build/test/checkpoints/preview; deployment needs target auth |
| 17 Proactive intelligence | DONE | opt-in, quiet-hours/rate-limited, no open model polling |
| 18 Self-repair | DONE | central health, circuits, backoff, watchdogs, isolation |
| 19 Performance | DONE | latency timeline, bounded payloads, lazy loading, resource metrics |
| 20 Visual experience | DONE | efficient Mini Orb/dashboard/Agent Space |
| 21 Security | DONE | approval, identity boundary, secrets/redaction, remote scopes/audit |
| 22 Testing | DONE | unit/integration/load/security/browser/voice/recovery scenarios |
| 23 Observability | DONE | IDs, durations, outcomes, traces, diagnostics endpoints |
| 24 GitHub research | DONE | adapter/license decisions in `ZENO_GITHUB_INTEGRATIONS.md` |

## Opportunity component mapping

The requested names are capability roles over registered agents, not duplicate
permanent agents:

| Component | Existing agent |
|---|---|
| OpportunityScout / MarketResearchAgent | ARIS |
| Competition / Freelance / Pricing / SEO | TITAN |
| SkillGapAgent | KATE |
| ContentAgent | ZEAL |
| ProductBuilderAgent | TOSIN |
| AnalyticsAgent | ORACLE |

They wake only through real delegation. ZENO stays master and synthesizes the
final result.
