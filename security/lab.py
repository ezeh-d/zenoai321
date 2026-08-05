"""
Security learning lab.

The offensive knowledge here is EDUCATION, not weapons: it explains how attacks
work so you can find and fix them, and points to environments where practicing
attacks is legal. No working exploits, no malware, no tooling aimed at systems
you don't own. Learn the concepts; practice on targets that grant permission.
"""
from __future__ import annotations

TOPICS = {
    "xss": (
        "Cross-Site Scripting: untrusted input is rendered as HTML/JS so an "
        "attacker's script runs in a victim's browser. Defend with context-aware "
        "output encoding, a Content-Security-Policy, and never injecting raw input "
        "into the DOM."
    ),
    "sqli": (
        "SQL Injection: input concatenated into a query changes its logic. Defend "
        "with parameterized queries, least-privilege DB accounts, and validation."
    ),
    "csrf": (
        "Cross-Site Request Forgery: a victim's browser is tricked into sending an "
        "authenticated request. Defend with anti-CSRF tokens, SameSite cookies, and "
        "Origin/Referer checks."
    ),
    "authz": (
        "Broken access control: users reach data/actions they shouldn't. Enforce "
        "authorization server-side on every request, deny by default, never trust "
        "the client to enforce roles."
    ),
    "ssrf": (
        "Server-Side Request Forgery: the server is coerced into requesting an "
        "attacker-chosen URL. Defend with allowlists, blocking internal ranges, and "
        "validating/normalizing URLs."
    ),
    "recon": (
        "Reconnaissance in AUTHORIZED testing = mapping a target you're allowed to "
        "test (open ports, services, versions) with tools like nmap. Only against "
        "systems you own or have written permission for."
    ),
    "hardening": (
        "Hardening = shrinking attack surface: patch promptly, disable unused "
        "services/ports, enforce MFA, least privilege, encrypt at rest/in transit, "
        "and keep audited logs."
    ),
}

LABS = """
Legal, authorized places to practice attack & defense:
  - TryHackMe        guided rooms, beginner-friendly        tryhackme.com
  - Hack The Box     vulnerable machines + academy          hackthebox.com
  - PortSwigger Web  free hands-on web-security labs         portswigger.net/web-security
  - OWASP Juice Shop deliberately vulnerable app (local)    owasp.org/www-project-juice-shop
  - DVWA             'Damn Vulnerable Web App', run locally  github.com/digininja/DVWA
  - VulnHub          downloadable vulnerable VMs            vulnhub.com

Golden rule: only test systems you own or are explicitly authorized to test.
Unauthorized access is a crime in most countries, whatever the intent.
"""


def learn(topic: str = "") -> str:
    topic = (topic or "").lower().strip()
    if topic in ("", "topics", "help"):
        return "Security topics: " + ", ".join(TOPICS) + ", labs"
    if topic == "labs":
        return LABS
    if topic in TOPICS:
        return TOPICS[topic]
    return (f"No note on '{topic}'. Known: {', '.join(TOPICS)}, labs.")
