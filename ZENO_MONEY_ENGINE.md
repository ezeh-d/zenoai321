# ZENO Opportunity Engine

## Purpose

`OpportunityEngine` helps Divine compare legitimate ways to earn online using
explicit evidence. It does not promise income, fabricate demand, spam people,
transact, or convert a score into financial advice.

## Workflow

`GOAL -> RESEARCH PLAN -> DATED OBSERVATIONS -> NINE FACTORS -> SCORE ->
OWNER REVIEW -> EXISTING BUILDER/OUTREACH TOOLS -> REAL RESULT -> REVALIDATE`

## Evidence model

Every observation is `FACT`, `ESTIMATE`, `ASSUMPTION`, `OPINION`, or
`EXPERIMENT_RESULT`. Facts/experiments require a source or local evidence
reference. Sources retain no query string/fragment. Expired observations are
excluded from current evidence whenever the record is read.

## Opportunity score

| Factor | Weight | Direction |
|---|---:|---|
| skill fit | 18% | higher is better |
| startup cost | 8% | lower is better |
| time to first result | 12% | lower is better |
| market demand | 20% | higher is better |
| competition | 10% | lower is better |
| repeatability | 12% | higher is better |
| scalability | 10% | higher is better |
| risk | 6% | lower is better |
| estimated effort | 4% | lower is better |

All factors are supplied on 0-10. The result is a transparent 0-100
**relative opportunity score**, not income probability. Missing/out-of-range
factors are rejected instead of invented.

## Roles and tools

ARIS researches; TITAN compares market/competition/pricing; KATE identifies
skill gaps; ZEAL handles content; TOSIN builds; ORACLE analyses. ZENO owns the
plan and synthesis.

- `opportunity_plan`: evidence collection plan.
- `opportunity_assess`: persist factors/observations.
- `opportunity_list` / `opportunity_get`: current/expired evidence.
- `opportunity_delete`: confirmation-gated; never deletes projects.

All five schemas stay outside ordinary turns and load only for a matching
request or explicit group activation.

## Safety

- no guaranteed earnings, spam, fake testimonials/identities, deception,
  copyright theft, or platform bypass;
- no purchase, payment, trade, transfer, or contract execution;
- consequential outreach/publishing keeps the existing confirmation gate;
- stale market facts must be revalidated.
