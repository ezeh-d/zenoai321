# ZENO Job Scout Report

Date: 2026-08-18

`JobScout` accepts real observed job/freelance postings from the existing
browser and research systems, normalizes the required 24-field schema, keeps a
canonical source URL and preserves provenance. Exact and near duplicates are
detected using stable fingerprints and normalized similarity. The scorer uses
16 named factors and returns its factor values, weights, total and category;
it never describes the score as a guarantee.

Platform policies exist for Indeed, LinkedIn, Upwork, Fiverr, Freelancer,
company portals and generic boards. No automatic poller or browser preload was
added. Authentication prompts, MFA/OTP, passkeys, CAPTCHA and security checks
pause the workflow for the owner.

Security tests verified rejection of embedded prompt injection, credential
requests, pay-first scams, gift-card/crypto requests, cheque forwarding and
remote-access installation. Test opportunities are tagged `TEST_DATA` and are
not included in real opportunity or revenue analytics.

Limit: production discovery quality depends on the evidence supplied by the
live page/research tool. ZENO does not claim unrestricted scraping or API access
where a platform has not granted it.
