# ZENO Mobile Companion API — v1

For the developer building the companion at `app.zenoassitant.com`.

**This document describes what is actually implemented.** Anything not
listed here does not exist yet. Verified end-to-end against a running server
on 2026-08-07.

---

## Base URL

| Environment | Base |
|---|---|
| Production (planned) | `https://api.zenoassitant.com` |
| Local development | `http://127.0.0.1:8765` |

Remote access is **off by default**. With `REMOTE_ACCESS_ENABLED` unset,
every authenticated endpoint returns `503` and the CORS allow-list is empty.

## CORS

Allowed origins are an explicit list — never `*`:

- `https://zenoassitant.com`
- `https://app.zenoassitant.com`
- `http://localhost:{8765,5173,3000}` **only** when `REMOTE_DEV_MODE=true`

Allowed headers: `Content-Type`, `Authorization`, `X-Zeno-CSRF`.
Methods: `GET`, `POST`, `OPTIONS`. Credentials allowed.

---

## Authentication

ZENO uses **WebAuthn/passkeys**. The phone's fingerprint or face is handled
entirely by the phone's OS and browser — **ZENO never receives biometric
data**, only a public key and signed assertions.

Send the session either way:

```http
Authorization: Bearer <session-token>     # use this from app.zenoassitant.com
Cookie: zeno_phone_session=<session-token> # same-origin only
```

> **Use the Bearer header.** The cookie is `SameSite=strict`, so a browser
> will *not* send it from `app.zenoassitant.com` to `api.zenoassitant.com`.
> Cookie-borne writes additionally require `X-Zeno-CSRF`; Bearer requests do
> not, because a browser never attaches them automatically.

Sessions last **30 minutes**. Revoking or locking a device invalidates its
sessions immediately.

### Pairing flow (QR)

```
Desktop ZENO                     Phone
  POST /api/v1/… (desktop-only)
  create_pair() ──► QR + 8-digit manual code
                                 scan → open https://<host>/pair?token=…
  POST /api/phone/pair/options  ◄── {token, name}
       ──► WebAuthn creation options
                                 navigator.credentials.create()
  POST /api/phone/pair/complete ◄── {credential, challenge}
       ──► {state: "PENDING_APPROVAL", device_id}
  Owner approves on the desktop → device becomes TRUSTED
```

Pairing tokens are **cryptographically random, single-use, 5-minute expiry**,
invalidated on success, and a new pairing cancels any older unconsumed one.
The QR carries only the pairing token — never a permanent credential.

### Login (already paired)

```
POST /api/phone/login/options   {device_id}      → assertion options
POST /api/phone/login/complete  {credential, challenge}
                                                 → {device_id, csrf} + session cookie
```

WebAuthn ceremonies stay on the existing `/api/phone/*` routes; `/api/v1/*`
is everything after you hold a session.

---

## Request / response format

Every command carries a `request_id` you choose, echoed back for tracing.

```json
{ "request_id": "abc123", "type": "command",
  "message": "Open Chrome", "timestamp": "2026-08-07T18:20:00Z" }
```

```json
{ "request_id": "abc123", "status": "success",
  "message": "Chrome opened.", "timestamp": "2026-08-07T18:20:04Z",
  "version": "v1", "data": { "category": "CONTROL", "tools": ["open_app"] } }
```

| `status` | HTTP | Meaning |
|---|---|---|
| `success` | 200 | Done; `message` is ZENO's reply |
| `pending` | 202 | Accepted, still running — watch the socket |
| `error` | 400 | Malformed request, or ZENO failed |
| `denied` | 403 | Refused by policy — `data.category` says why |
| `rate_limited` | 429 | `data.retry_after` seconds |

Request types: `command`, `status`, `ping`.
Message limit: **4000 characters**.

---

## Endpoints

All require a session unless marked.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/meta` | **No auth.** Protocol version, feature flags. Reveals nothing about the machine. |
| GET | `/api/v1/status` | Connection state, device name, scopes |
| POST | `/api/v1/command` | **The main entry point** |
| GET | `/api/v1/tasks` | Active work in phone-facing states |
| GET | `/api/v1/agents` | Sub-agent names + idle/working |
| GET | `/api/v1/memory/recent?limit=10` | Recent conversation turns only |
| GET | `/api/v1/devices` | Paired devices |
| POST | `/api/v1/devices/revoke` | `{device_id}` — omit to revoke self |
| POST | `/api/v1/logout-all` | Ends all sessions (pairings survive) |
| GET | `/api/v1/website/projects` | Website Studio projects |
| POST | `/api/v1/website/action` | `{action, project}` — allow-listed |
| GET | `/api/v1/audit?limit=50` | Recent remote actions |

### Connection states

`ONLINE` · `OFFLINE` · `CONNECTING` · `RECONNECTING` · `DEGRADED`

`DEGRADED` is returned with `reasons[]` — no healthy model provider, tunnel
configured but not running, or no domain configured yet.

### Website Studio actions

Only these five. Anything else returns `denied`.

`status` · `checkpoint` · `check` · `preview` · `continue`

They are phrased as ordinary ZENO requests and routed through the normal
brain, so **every Website Studio safety rule still applies**. There is no
shell access from the phone.

---

## WebSocket

```
wss://api.zenoassitant.com/ws/phone
Authorization: Bearer <session-token>
```

The upgrade is rejected (`4403`) if `Origin` is not on the allow-list, and
(`4429`) if you reconnect too often. `4401` means the session is invalid,
locked or revoked.

Server → client frames:

```json
{"type": "connected", "device_id": "…"}
{"type": "heartbeat"}
{"type": "task",    "task_id": "…", "state": "working", "percent": 60}
{"type": "website", "project": "…", "state": "building", "preview_url": "…"}
{"type": "notification", "title": "…", "body": "…", "level": "info"}
```

A `heartbeat` arrives roughly every 10s and doubles as a revocation check —
if the device was revoked, the socket closes instead.

**Reconnect with backoff.** Do not retry in a tight loop; the server bounds
reconnects at 20 per 5 minutes per client.

### Task states

`queued` · `thinking` · `working` · `waiting` · `testing` · `completed` ·
`failed` · `cancelled`

### Website Studio states

`planning` · `coding` · `building` · `fixing` · `preview_ready` ·
`completed` · `failed`

---

## Command categories — what a phone may do

Classified server-side before anything runs:

| Category | Examples | From a phone |
|---|---|---|
| `SAFE` | questions, status, reading notes | ✅ |
| `CONTROL` | open an app, build a site, checkpoint | ✅ then the desktop's normal confirmation rules |
| `SENSITIVE` | firewall, credentials, admin, system | ❌ always |
| `FINANCIAL` | transfers, payments, purchases, crypto | ❌ always |

This exists for the **stolen-phone case**: a device that already passed
WebAuthn still cannot reach money or security settings.

`CONTROL` passing this layer does not bypass anything — it then meets the
same permission engine and confirmation gate as a command typed on the
desktop.

## Rate limits

| Bucket | Budget |
|---|---|
| `command` | 60 / minute |
| `login` | 8 / 5 min |
| `pair` | 5 / 15 min |
| `auth_failure` | 10 / 10 min |
| `ws_connect` | 20 / 5 min |

Limits are per identity, so one attacker cannot lock out the owner.

## Errors

`401` no/invalid session · `403` denied by policy or origin · `429` rate
limited · `503` remote access disabled.

Error bodies never contain tokens, and the audit log stores only timestamp,
device, category, request id, action and result.

---

## Not yet implemented

- **TTS/voice response references** — replies are text only.
- **Push notifications** — events arrive over the WebSocket while connected;
  there is no APNs/FCM provider wired (the abstraction is there, no provider
  is hardwired).
- **Voice transcript upload** — send the transcript as a normal `command`.
- **Refresh-token rotation** — sessions expire at 30 min and require a fresh
  WebAuthn assertion rather than refreshing.
