# ZENO Security Model

## Trust boundaries

1. The signed-in Windows desktop and loopback API are local, not public.
2. Phone access requires an approved device, expiring/revocable session,
   scopes, CSRF/origin protection, and secure transport.
3. Voice identity personalizes/private-gates but never authorizes a sensitive
   action by itself.
4. Provider/model/tool output is untrusted until the common execution boundary
   validates capability, arguments, autonomy, confidence, and approval.

## Autonomy levels

| Level | Meaning |
|---|---|
| 0 | talk only; no tools |
| 1 | read-only or reversible low-risk action |
| 2 | normal configured desktop/browser action |
| 3 | explicit owner confirmation required |
| 4 | structurally blocked from automatic execution |

Purchases, payments, transfers, credential/security changes, important
deletion, public posting, consequential submissions, elevation, and contracts
are Level 3 or 4. Opportunity analysis cannot move money.

## Execution controls

- Every tool uses `run_tool`; specialists/workers cannot bypass it.
- Capability profiles restrict tools, roots, services, network, and
  credentials at the execution boundary.
- Coding resolves only configured roots, blocks dangerous commands, bounds
  subprocess time/output, records changed files, and redacts secrets.
- Browser automation honors domain policy and never bypasses CAPTCHA.
- Plugins require manifests/approval, run through the capability sandbox, and
  now load only on explicit admin/extended access.

## Data controls

- `.env`, keys, profiles, cookies, logs, caches, audio, and device material are
  ignored and were not found in tracked paths.
- Audit/trace payloads redact secret-shaped keys and bound content/size.
- Memory policy rejects credentials and sensitive authentication material.
- Opportunity source URLs discard query strings/fragments so tokens are not
  retained as citations.

## Evidence rule

A normal return is `RETURNED/UNVERIFIED`, not success. Only a verified
postcondition produces `COMPLETED/VERIFIED`. The central trace now uses the
same classifier as the tool/audit/Event Bus path.

## Remaining limits

- Trusted local Python plugins are not a perfect OS sandbox.
- The restricted local coding backend is not a container security boundary.
- Owner voice accuracy awaits consented enrollment/evaluation; voice remains
  insufficient for sensitive authorization regardless.
