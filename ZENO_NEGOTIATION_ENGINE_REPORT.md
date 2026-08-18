# ZENO Negotiation Engine Report

Date: 2026-08-18

The negotiation component stores owner-confirmed minimum, target and premium
pricing, currency, delivery time, revision allowance, rush fee and scope. It
produces a recommendation and draft response; it does not accept work or create
a binding agreement.

Offers below the owner's minimum, unusual terms or incomplete pricing return
`OWNER DECISION REQUIRED`. Contract creation requires client, project, scope,
deliverables, deadline, price, currency, payment method, milestones, revisions,
risks and terms. Every contract remains `OWNER CONTRACT APPROVAL REQUIRED`
until the owner approves it with evidence. Blocked clients cannot proceed.

Tests cover below-minimum offers, unusual terms, missing terms, blocked clients,
positive prices, revision bounds and owner approval.

Limit: negotiation guidance is deterministic business assistance, not legal
advice, and no signature or external contractual commitment is automated.
