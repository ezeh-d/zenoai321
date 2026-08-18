# ZENO Application Engine Report

Date: 2026-08-18

Applications default to `APPROVAL` mode. The engine requires a verified owner
profile, checks application duplication and a bounded daily limit, identifies
truthful skill gaps, and creates unique immutable application folders containing
a tailored CV, proposal and quality-control record. The master CV is never
overwritten.

Unverified skills or experience cannot be added to profile variants. Missing
facts return `OWNER INFORMATION REQUIRED`. Platform adapters currently require
owner submission unless an approved submission API is configured. The manual
submission recorder requires explicit owner approval plus evidence and records
what happened; it does not click the external submit control itself.

Tests cover truthful profile enforcement, missing-profile failure, version
uniqueness, artifacts, duplicate prevention, rate limiting, authentication
boundaries, owner evidence and the full simulated application lifecycle.

Limit: ZENO cannot complete CAPTCHA, MFA or owner-only platform confirmations,
and it does not report an external application as submitted from a draft.
