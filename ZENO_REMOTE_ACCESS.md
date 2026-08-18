# ZENO Remote Access

## Status

| capability | state |
|---|---|
| LAN phone access (mic, chat, companion) | **working** |
| Fail-closed remote boundary | **working** |
| Risk classification for remote actions | **working** |
| Desktop gateway (local half) | **partial** |
| Owner authentication | **NOT BUILT** |
| Access from outside the LAN | **NOT BUILT** |
| PWA install | **NOT BUILT** |

**You cannot currently open ZENO from a coffee shop.** LAN only.

## What works today

The phone listener on port 8768 serves an allow-listed surface to devices on
the same network: `/phone`, `/pair`, `/mic`, `/api/phone/*`, `/ws/phone`.
Pairing is per-device with a scoped permission — the phone-as-microphone
trust is `REMOTE_AUDIO_SEND` only, and it does not grant desktop control,
filesystem, email, shell, memory or administrator access.

## The boundary

`remote_access/boundary.decision()` runs on every HTTP and WebSocket request
and returns `(allowed, status, reason)`.

```
loopback peer, no forwarded headers   → allowed
forwarded headers, remote disabled    → 503
direct LAN peer, companion disabled   → 503
path not in the allow-list            → 403
otherwise                             → allowed
```

**Deny by default.** A new route is unreachable remotely until someone adds
its prefix deliberately. `/api/phone/admin*` is refused unconditionally.

This is why the eight new `/api/social/*` routes are desktop-only without any
extra code: they were never allow-listed. A test asserts it by making a real
request from `192.168.1.50` and requiring 403 or 503.

## Risk classes (Phase 8)

`remote_access/policy.py`:

| class | examples |
|---|---|
| LOW | ask a question, read status, open a browser |
| MEDIUM | create a normal project file, open an app |
| HIGH | delete files, install software |
| CRITICAL | change security configuration, anything financial |

Remote access adds gates; it never removes one. An action requiring
confirmation locally still requires it remotely.

## Desktop gateway

`remote_access/gateway.py` implements the **local** half:

- `connection_status()` — ONLINE / OFFLINE / BUSY / DEGRADED
- `handle(request, scopes=...)` — scope-checked dispatch into ZENO
- `record(...)` / `audit_log(...)` — every remote request, with its decision

The design is outbound-only: the Windows machine dials the cloud and holds
the connection open. **It never opens a port to the internet.** There is no
cloud endpoint to dial yet, so this half runs and reports OFFLINE.

When "Open VS Code on my computer" eventually works, the path is:

```
cloud → authenticated owner → gateway → local ZENO → Windows control
      → verify the action happened → result returned
```

The verification step is not optional. ZENO already refuses to claim a
browser click it did not perform; the same rule applies here.

## OWNER ACTION REQUIRED

Remote access beyond the LAN is blocked on four things, all of them yours:

1. **A host** for ZENO Cloud — a monthly cost, and a choice I will not make.
2. **A domain with TLS** — passkeys bind to a domain and cannot be registered
   against a bare IP.
3. **Google OAuth credentials** for the approved Gmail.
4. **A decision on device approval** — whether a new device requires
   confirmation from an already-trusted one.

*What ZENO needs afterward:* the domain, the OAuth client id and secret in the
keyring, and the host's outbound URL for the gateway.

## What must be built before the internet sees any of this

`OwnerAuthService`, with: login, logout, session expiry, token refresh, a
device and session list, and revocation. Until it exists, opening ZENO to the
internet would expose desktop control and social publishing to anyone who
finds the URL.

That is why remote social control is closed rather than open. It is a missing
feature, and closing the door is the correct response to a missing lock — not
a substitute for one.
