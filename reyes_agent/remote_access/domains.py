"""Which origins ZENO trusts, and nothing else.

WHY THIS IS ITS OWN MODULE
--------------------------
Origin policy is a security boundary, and a security boundary spread across
route handlers is a security boundary nobody can audit. Everything that
decides "may this caller talk to us" lives here: the CORS allow-list, the
WebSocket origin check, and the split between production and development.

THE RULES THAT DO NOT BEND
--------------------------
* An authenticated API never sends `Access-Control-Allow-Origin: *`. With
  credentialed requests that combination is rejected by browsers anyway,
  and reaching for it is how people end up disabling credentials instead.
* Localhost is allowed ONLY when REMOTE_DEV_MODE is on. A production build
  that trusts `http://localhost:5173` trusts any page on the owner's
  machine, including a malicious one.
* An empty allow-list means empty. It never degrades to "allow everything"
  because the domain was not configured yet.

The domain is `zenoassitant.com` -- that spelling is the owner's, and it is
used verbatim.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from reyes_agent import config

# Sub-domains the architecture plans for. Used to derive sensible defaults
# when only ZENO_PUBLIC_DOMAIN is set.
SUBDOMAINS = ("app", "api", "status", "admin")

# Development origins. Never included unless REMOTE_DEV_MODE is on.
DEV_ORIGINS = (
    "http://localhost:8765", "http://127.0.0.1:8765",
    "http://localhost:5173", "http://127.0.0.1:5173",   # Vite default
    "http://localhost:3000", "http://127.0.0.1:3000",   # Next default
)


def _normalise(origin: str) -> str:
    """Scheme + host + explicit port only -- never a path."""
    text = str(origin or "").strip().rstrip("/")
    if not text:
        return ""
    parts = urlsplit(text if "//" in text else f"https://{text}")
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def public_domain() -> str:
    return str(getattr(config, "ZENO_PUBLIC_DOMAIN", "") or "").strip().lower()


def app_origin() -> str:
    configured = _normalise(getattr(config, "ZENO_APP_ORIGIN", ""))
    if configured:
        return configured
    domain = public_domain()
    return f"https://app.{domain}" if domain else ""


def api_origin() -> str:
    configured = _normalise(getattr(config, "ZENO_API_ORIGIN", ""))
    if configured:
        return configured
    domain = public_domain()
    return f"https://api.{domain}" if domain else ""


def site_origin() -> str:
    domain = public_domain()
    return f"https://{domain}" if domain else ""


def dev_mode() -> bool:
    return bool(getattr(config, "REMOTE_DEV_MODE", False))


def allowed_origins() -> list[str]:
    """Exactly who may call the authenticated API. Order is stable."""
    origins: list[str] = []
    for candidate in (site_origin(), app_origin()):
        if candidate and candidate not in origins:
            origins.append(candidate)
    if dev_mode():
        for candidate in DEV_ORIGINS:
            if candidate not in origins:
                origins.append(candidate)
    return origins


def is_allowed_origin(origin: str) -> bool:
    """The single origin test. Used by CORS and by the WebSocket handshake.

    A missing Origin header is NOT treated as allowed: browsers always send
    one on cross-origin requests and on WebSocket upgrades, so an absent
    header on a remote connection is a non-browser client that must
    authenticate on its own merits, not ride in on an origin exemption.
    """
    normalised = _normalise(origin)
    if not normalised:
        return False
    return normalised in allowed_origins()


def configured() -> bool:
    """Whether a real public domain has been set up yet."""
    return bool(public_domain() or app_origin())


def expected_dns() -> list[dict[str, str]]:
    """What the owner will need at the registrar -- stated, never applied.

    Deliberately does not invent targets: a CNAME needs the tunnel's own
    hostname, which only exists once `cloudflared` has created the tunnel.
    The placeholder is honest about that.
    """
    domain = public_domain() or "zenoassitant.com"
    return [
        {"type": "CNAME", "name": "api", "value": "<tunnel-id>.cfargotunnel.com",
         "purpose": f"api.{domain} -> the Cloudflare Tunnel that reaches this machine",
         "note": "value comes from `cloudflared tunnel create`; do not guess it"},
        {"type": "CNAME", "name": "app", "value": "<companion-host>",
         "purpose": f"app.{domain} -> wherever the mobile companion is hosted",
         "note": "set by the companion's host (Vercel/Netlify/Pages); not this machine"},
        {"type": "A or CNAME", "name": "@", "value": "<website-host>",
         "purpose": f"{domain} -> the public ZENO website",
         "note": "static host of the owner's choosing"},
    ]


def status() -> dict[str, object]:
    """Diagnostics for the owner and for the mobile developer."""
    return {
        "public_domain": public_domain(),
        "site_origin": site_origin(),
        "app_origin": app_origin(),
        "api_origin": api_origin(),
        "allowed_origins": allowed_origins(),
        "dev_mode": dev_mode(),
        "configured": configured(),
        "remote_access_enabled": bool(getattr(config, "REMOTE_ACCESS_ENABLED", False)),
        "note": ("Origins are an allow-list. An unconfigured domain means an EMPTY "
                 "list, never a wildcard -- remote access simply stays closed."),
    }
