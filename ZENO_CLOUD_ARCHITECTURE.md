# ZENO Cloud Architecture

## Status: DESIGN + partial. Read this section first.

The brief asked for ZENO to become reachable from anywhere. **It is not yet,
and nothing in this document should be read as claiming it is.**

What exists today:

| layer | state | evidence |
|---|---|---|
| ZENO CORE | **built** | `reyes_agent/` — agents, memory, router, tools, 1096 tests |
| Local API + WebSocket | **built** | `web.py`, FastAPI, loopback + phone listener |
| Remote boundary | **built** | `remote_access/boundary.py`, fail-closed allow-list |
| Desktop gateway | **partial** | `remote_access/gateway.py` — status, audit, request handling |
| Risk classes | **built** | `remote_access/policy.py` |
| Social system | **built + wired this pass** | see `ZENO_SOCIAL_ARCHITECTURE.md` |
| CI pipeline | **built** | `.github/workflows/ci.yml` |
| **Owner authentication** | **NOT BUILT** | no `OwnerAuthService` anywhere |
| **Cloud deployment** | **NOT BUILT** | no host, no domain, no `deploy.yml` |
| **Web/PWA client** | **NOT BUILT** | no manifest, no service worker for the main app |
| **Cloud database** | **NOT BUILT** | all state is local SQLite |

**ZENO is not online.** It runs on the owner's Windows machine and is
reachable on the LAN through the phone listener. That is the honest position.

## Target

```
OWNER  →  phone / tablet / computer
            ↓  HTTPS
       ZENO WEB (PWA)
            ↓  REST + WebSocket, authenticated
       ZENO CLOUD API
            ↓
       ZENO CORE — reasoning, memory, agents, routing, approvals
            ↓                            ↕ outbound tunnel only
       ZENO WORKER                  DESKTOP GATEWAY
       scheduled jobs                    ↕
                                    WINDOWS ZENO
                                    local apps, files, automation
```

The desktop connection is **outbound only**. The Windows machine never opens
a port to the internet. This is the single most important property in the
design and the reason the gateway is shaped the way it is.

## What is built, honestly

### The remote boundary — fail-closed, and it works

`remote_access/boundary.py` decides every request. Anything not explicitly
allow-listed is refused for non-loopback callers. It distinguishes:

- **forwarded remote** — Cloudflare/Tailscale headers present
- **direct remote** — a real non-loopback socket peer, which is how the LAN
  phone listener is reached
- **loopback** — the desktop itself

A real bug this already caught: treating direct-LAN requests as loopback had
exposed every desktop route on port 8768. The socket peer is now the
authority.

The eight new `/api/social/*` routes inherit this and are **refused for
remote callers** — verified by a test that makes a request from
`192.168.1.50`.

### Risk classes — built

`remote_access/policy.py` classifies actions LOW / MEDIUM / HIGH / CRITICAL,
matching Phase 8. Remote access does not remove any existing approval
requirement.

### Desktop gateway — partial

`remote_access/gateway.py` has connection status (ONLINE/OFFLINE/BUSY/
DEGRADED), an audit trail, scope-checked request handling and dispatch into
ZENO. **What it lacks is the other end**: there is no cloud service for it to
dial out to.

## OWNER ACTION REQUIRED — what blocks the rest

Everything below needs a decision only the owner can make. These are not
engineering problems.

### 1. A host, and a paid decision

ZENO Cloud needs somewhere to run. Fly.io, Railway, Render and a small VPS
all work. **This costs money monthly** and I will not pick a provider or
create an account.

*What ZENO needs afterward:* the host name, the region, and whether the
database is Postgres or hosted SQLite.

### 2. A domain

Needed for OAuth redirect URIs and passkey registration — passkeys are bound
to a domain and cannot be tested on a bare IP.

*What ZENO needs afterward:* the domain, pointed at the host, with TLS.

### 3. Google OAuth credentials

Console → OAuth 2.0 Client ID → Web application, with the redirect URI on the
domain above.

*What ZENO needs afterward:* `GOOGLE_OAUTH_CLIENT_ID` and
`GOOGLE_OAUTH_CLIENT_SECRET` in the keyring, plus the owner's Gmail as the
sole approved account.

### 4. Instagram and TikTok credentials

See `ZENO_INSTAGRAM_SETUP.md` and `ZENO_TIKTOK_SETUP.md`. TikTok's Content
Posting API needs platform review, which takes days.

## Deliberate order

The brief said not to rush to Instagram and TikTok before the cloud and
authentication architecture is secure. That is why this pass **wired the
social subsystem locally and left remote access closed** rather than opening
a path to it. Publishing controls reachable from the internet without
`OwnerAuthService` would be exactly the mistake the brief warned against.

Sequence:

1. `OwnerAuthService` — sessions, expiry, refresh, device list, revocation
2. Cloud API skeleton with auth in front of everything
3. Deploy to a real host *(blocked on the owner's decisions above)*
4. Desktop gateway outbound client
5. Web/PWA client
6. Add `/api/social/*` to the authenticated remote surface — **only then**

## Rollback

`deploy.yml` does not exist. When it does it must keep the last known good
release and restore it on a failed health check. Until there is a host, there
is nothing to roll back, and pretending otherwise would be a decorative
workflow file.
