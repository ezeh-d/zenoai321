# AVA — Offensive & Defensive Security

## What AVA is

ZENO's red-and-blue-team security specialist. She does real offensive work —
recon, scanning, enumeration, vulnerability analysis, web-app testing, password
attacks, exploitation, post-exploitation — and the defensive side — forensics,
detection, hardening. STARK is the passive defensive monitor; AVA is the one
who actively tests.

She is a full specialist in ZENO's existing hierarchy, with her own six-worker
team:

| worker | side | role |
|---|---|---|
| RECON | red | reconnaissance & OSINT |
| BREACH | red | scanning & exploitation |
| CIPHER | red | password & credential attacks |
| PHANTOM | red | web application testing |
| WARDEN | blue | defense & hardening |
| AUTOPSY | blue | forensics & incident response |

## The one rule that makes her a tool and not a weapon

**AVA operates only on targets the owner has personally authorized.**

This is not a limit on her capability — against an authorized target she runs
the full chain, real Nmap, real Metasploit, real shells. It is a *target
list*, and it is the exact thing that separates a penetration tester from a
criminal. Every professional engagement runs under the same rule: a signed
scope, a target list, a start and end date.

The authorization store (`security/testing/authorization.py`) is the spine.
Every operation that touches a target asks it first. A target that is not
authorized gets a refusal and instructions to authorize it — nothing else.

### What counts as authorization

The owner attests one of:

| attestation | meaning |
|---|---|
| `i_own_it` | the owner owns the target |
| `written_permission` | the owner holds written permission to test it |
| `ctf_or_lab` | a deliberately vulnerable lab, CTF or range |
| `bug_bounty_scope` | in scope for a published bug-bounty programme |
| `sanctioned_public` | a host whose owner published permission to test it |

"I want to test it" is **not** on this list, deliberately. Wanting to attack a
server is not permission to, and no attestation encodes it.

### What the owner cannot authorize

The store refuses to scope third-party infrastructure the owner cannot consent
for — `paypal.com`, `google.com`, public DNS resolvers, major platforms — and
refuses giant public ranges as mass-targeting. The owner may own a server;
they do not own Stripe.

## Refused regardless of scope

Some techniques harm beyond any single target, so authorization does not
enable them. `engagement.py` refuses, whatever the scope:

- denial of service / DDoS / stress-flooding
- mass or untargeted attacks ("scan the whole internet")
- self-propagating or destructive malware (worms, ransomware, wipers)
- supply-chain compromise (poisoning a package everyone downstream pulls)
- real-world fraud (draining a wallet, carding)

A reference scam/DoS goal scores a refusal with the technique named. Ordinary
pentest work — "scan for open ports, find vulns, get a shell, escalate" — is
**not** caught by this and plans in full.

## The toolkit — 87 tools, offensive and defensive

`catalog.py` is a structured reference to the standard security tools across
13 kill-chain phases: Nmap, masscan, Burp, ZAP, sqlmap, ffuf, gobuster,
Nikte, Metasploit, Impacket, CrackMapExec, BloodHound, Mimikatz, Rubeus,
Hydra, Hashcat, John, Responder, Aircrack-ng, Wireshark, Volatility, Ghidra,
Sigma, Suricata, osquery, Wazuh, and the rest. Each is tagged offense /
defense / dual and marked whether it touches a target (and so needs scope).

Nothing whose purpose is indiscriminate harm is in it — no DDoS stresser, no
ransomware builder — and a test asserts that.

## Real authorized targets, in one command

The point of the scope rule is not to make targets hard to get — it is to make
them *legitimate*. Three ways to get real ones fast:

**1. Publicly-sanctioned hosts.** Real servers whose owners published
permission to test them — `scanme.nmap.org` (Nmap), the `*.vulnweb.com` family
(Acunetix), `demo.testfire.net` (IBM). `security_sanctioned_targets` lists them
with the sanction each rests on, and authorizes one on request. Real machines,
on the public internet, legal to hit because the owner said so.

**2. Bug-bounty scope.** `security_import_bounty_scope` takes a programme's
published scope (in-scope and out-of-scope, pasted or as JSON) and authorizes
the in-scope assets and *only* those. Out-of-scope entries are skipped;
third-party assets are refused even if listed. Wildcards (`*.example.com`) are
supported and cover subdomains. This is real production infrastructure you are
invited, in writing, to attack — and paid when you find something.

**3. A local vulnerable lab.** `security_lab` stands up the actual
industry-standard vulnerable applications — DVWA, OWASP Juice Shop, WebGoat —
as real servers in Docker on localhost, and auto-authorizes them (localhost is
yours). Real SQL injection, real shells, real privilege escalation, against a
target with no one to authorize but you.

## Tools

| tool | gated | what it does |
|---|---|---|
| `security_authorize` | confirm | add a target to scope, with attestation |
| `security_scope` | — | list authorized targets |
| `security_revoke` | confirm | remove a target, or clear all |
| `security_toolkit` | — | the tools for a phase or task |
| `security_plan` | — | plan an assessment (scope-checked, refuse-listed) |
| `security_sanctioned_targets` | confirm | list / authorize sanctioned hosts |
| `security_import_bounty_scope` | confirm | load a bug-bounty programme's scope |
| `security_lab` | confirm | start/stop the local vulnerable lab |
| `security_authorization_log` | — | the scope audit trail |

Every tool that changes scope or touches a host requires confirmation. The
planning tools return methodology and real commands; running them is the
owner's deliberate act through ZENO's gated command path, not a side effect of
asking AVA to think.

## Not a privilege-escalation path

Each of AVA's six workers has a strict subset of her tools — a test asserts no
worker exceeds the parent — so delegating one level deeper can never reach a
capability AVA herself lacks.

## Tests

`tests/test_ava_security.py` — 47 tests. The scope gate gets the heaviest
coverage: unauthorized targets refused, third-party infrastructure un-grantable,
expiry, revocation, wildcards, and the refuse-list holding under an authorized
scope. Plus a live integration check that starts a real DVWA container and
confirms it answers HTTP with AVA authorized on it.

## Where the line is, plainly

AVA is fully capable. The exploitation is real. What she will not do is accept
a target nobody authorized — because that target field is the offense itself,
and no framing changes it. The authorized paths above (own systems, labs, bug
bounties, sanctioned hosts) are not a lesser version of the capability; they
are how the capability is used by people who keep their careers.
