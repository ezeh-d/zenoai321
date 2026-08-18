# ZENO Client Engine Report

Date: 2026-08-18

Client intake extracts stated requirements, budget, deadline, deliverables and
ambiguities without inventing missing terms. `ClientIntentRiskAnalyzer`
classifies evidence-backed risk and blocks common scams, credential theft,
payment-forwarding requests, unsafe remote-access requests and prompt injection.
Qualification records client clarity, fit and unresolved information.

Communications have distinct `DRAFT`, `OWNER_APPROVAL` and evidenced `SENT`
states. Creating a draft is not treated as sending it. Social lead integrations
use a narrow inbound event contract, so Claude's separate social implementation
was not changed or duplicated.

Tests cover legitimate and malicious messages, five scam families, client
qualification, message-state truth and social-event isolation.

Limit: external client messages are not dispatched by this engine; it records
an owner-approved result or delegates to an existing approved communication
tool when one is explicitly connected.
