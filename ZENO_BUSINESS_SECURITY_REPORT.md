# ZENO Business Security Report

Date: 2026-08-18

Confirmed controls:

- Approval is the default application mode.
- Owner-only actions are classified by the existing permission engine and are
  excluded from autonomous tool sets.
- Passwords, tokens, cookies, private keys, OTP/MFA values and similar secret
  fields are rejected from the career database and audit input.
- CAPTCHA, passkey, biometric and other security prompts pause for the owner.
- Prompt injection in opportunity/client text is treated as untrusted data.
- External submission, contract approval, delivery and payment verification
  require explicit owner evidence.
- Test data is tagged and excluded from production metrics and reputation.
- The Career dashboard/API remains loopback-only under the existing remote
  boundary middleware.
- Paths for application artifacts are engine-owned unique directories; the
  master profile/CV is not overwritten.
- No unbounded retries, threads, pollers or hidden browser sessions were added.

Adversarial tests covered traversal-shaped identifiers, credential storage,
malicious listings, scam messages, false submission/delivery/payment states,
failed agent work and missing postconditions.

Limits: platform terms and authentication still need live owner observation.
ZENO cannot make financial, legal or identity guarantees from software checks.
