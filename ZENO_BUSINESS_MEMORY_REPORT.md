# ZENO Business Memory Report

Date: 2026-08-18

Business memory is derived from the career engine's durable records, not model
claims. It reports owner-verified revenue, application response rate, proposal
conversion, projects won/delivered, average project value, observed platform
frequency and observed requested-skill frequency. Profitability is labelled an
`ESTIMATE` and includes all input assumptions.

Reputation reports only genuinely delivered projects and repeat clients.
Satisfaction remains unknown and testimonials remain zero unless genuine
owner-recorded evidence exists. Test/dry-run rows are excluded by default.

The store is local SQLite, transactionally updated, bounded on list reads and
opened lazily. Secrets and credential-shaped fields are rejected from records.

Tests verify real/test separation, revenue truth, response/conversion metrics,
skill-gap frequency, profitability labelling and non-fabricated reputation.

Limit: observed platform and skill frequency are not represented as global
market research; they describe only the real postings stored by ZENO.
