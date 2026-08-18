# ZENO Remote Access

## Status

| capability | state |
|---|---|
| Owner authentication (password, sessions, refresh, revocation) | **built** |
| Browser device approval | **built** |
| Command queue with approval gate | **built** |
| Windows outbound connector | **built** |
| Responsive web app / PWA | **built** |
| LAN phone access (mic, chat, companion) | **built, unchanged** |
| Fail-closed remote boundary | **built, unchanged** |
| Passkeys / WebAuthn for the web app | **architecture ready, needs a domain** |
| Cloud deployment | **NOT DEPLOYED** |

**ZENO is still not on the internet.** Everything below runs and is tested;
what is missing is a host and a domain, which are owner decisions. See
`OWNER ACTION REQUIRED`.

## The path a command takes

```
phone browser
  │  POST /api/owner/auth/login          password + nonce
  │      → httpOnly Secure cookies, CSRF token in the body
  │      → this browser is registered PENDING
  │
  │  (owner approves the browser at the desktop, once)
  │
  │  POST /api/owner/command             action + device_id
  ▼
ZENO API   ── session check
           ── CSRF check on every state-changing method
           ── action must be in REGISTERED_ACTIONS
           ── policy.evaluate(): FINANCIAL and SENSITIVE refused outright
           ── device must exist and be APPROVED
           ▼
        PENDING_APPROVAL          ← device actions wait for an owner decision
           │  POST /api/owner/approvals/{id}/decision
           ▼
        WAITING_FOR_DEVICE  (laptop offline)  or  QUEUED  (laptop connected)
           ▲
           │  the desktop DIALS OUT and pulls
Windows ZENO ── POST /device/claim      → IN_FLIGHT
             ── POST /device/ack        → ACKNOWLEDGED
             ── runs a registered TOOL, never a string from the network
             ── POST /device/complete   → DONE or FAILED, with the real result
```

Nine states, and they mean different things on purpose:
`PENDING_APPROVAL`, `WAITING_FOR_DEVICE`, `QUEUED`, `IN_FLIGHT`,
`ACKNOWLEDGED`, `DONE`, `FAILED`, `EXPIRED`, `CANCELLED`.

**"Queued" is never rendered as "done".** A test asserts a command whose
laptop has never sent a heartbeat reports `WAITING_FOR_DEVICE` and tells the
owner the device is offline.

## Nothing listens on the Windows machine

`reyes_agent/remote_access/desktop_agent.py` polls outward. No port is
opened, nothing is forwarded, and NAT/CGNAT are irrelevant. If the gateway
disappears the loop simply stops receiving work — the failure mode is "ZENO
goes quiet", not "ZENO is exposed".

Reconnection uses exponential backoff with **full jitter**, capped at 60s.
Without jitter every device that lost a gateway reconnects in lockstep and
knocks it over again.

## The desktop never executes a string from the network

`ACTION_TOOLS` maps a registered action name to a registered ZENO **tool**:

| action | tool | category |
|---|---|---|
| `ask` | the agent turn loop | READ_ONLY |
| `status` | `system_health` | READ_ONLY |
| `memory_recall` | `search_notes` | READ_ONLY |
| `agent_status` | `agent_roster` | READ_ONLY |
| `open_app` | `open_app` | STANDARD_DEVICE |
| `close_app` / `run_automation` | `open_app` | SENSITIVE_DEVICE |

Arguments are built by a function per action, so a payload cannot name a
parameter the builder does not pass. Application names are additionally
allow-listed. There is no branch that runs shell text, imports a named
module, or formats caller input into a command line.

Routing through the tool registry also means the remote path **inherits the
permission and confirmation architecture the desktop already has** — a tool
marked `requires_confirmation` still requires it.

### Two bugs this design caught

The first version of the executors called `Agent()`,
`desktop_app.open_application()`, `memory_manager.recall()` and
`agent_space.roster()`. **Four of those five do not exist.** They would have
failed on every command while looking implemented.
`test_every_action_maps_to_a_registered_tool` now fails if that ever recurs.

The second version passed `name=` to `open_app`, which takes `name_or_path`.
Every launch failed with "unexpected keyword argument".
`test_action_arguments_match_the_real_tool_schemas` reads the live schema.

## Authentication

`reyes_agent/auth/owner.py`.

- **scrypt** (n=2¹⁵, r=8), 348 ms per attempt on this machine. OpenSSL
  enforces a memory ceiling that rejects these parameters at its default, so
  `maxmem` is raised rather than the cost factor being weakened to fit.
- **Lockout** after 5 consecutive failures, 15 minutes, per identity.
- **Timing:** the password is verified even when the email is wrong, so a
  wrong email and a wrong password take the same time.
- **Sessions** 30 minutes; **refresh** 14 days and **single-use** — a stolen
  refresh token works at most once, and reuse finds nothing.
- **Cookies** `HttpOnly; Secure; SameSite=None`. The token is never in the
  JSON body and never in `localStorage`, so injected script cannot read it.
  Only the CSRF token is script-readable, which is required — it travels as a
  header, and alone it authenticates nothing.
- **CSRF** required on every POST/PUT/PATCH/DELETE.
- **Replay** every login needs a fresh nonce of ≥16 characters, single-use.
- **Revocation** per session or all at once; changing the password revokes
  everything.

Passwords are ≥12 characters and checked against a small list of the most
common. Every entry in that list is ≥12 characters — a shorter one is
unreachable, because the length check rejects it first. A test asserts it.

### Two gates a password alone does not pass

**The browser is a device.** First sign-in from a new browser registers it
`PENDING`; protected routes answer `403 PENDING DEVICE` until the owner
approves it at the desktop. A stolen password on an unknown browser gets a
session and nothing else.

**Device commands need an approval.** `open_app` lands in
`PENDING_APPROVAL`. A connected, approved laptop that polls the queue
receives **nothing** until the owner decides. Two tests cover this: one that
the device gets an empty claim, one that a denied command never reaches it.

## Local development

Session cookies are `Secure` outside development mode, which means a browser
on `http://localhost` **drops them silently** and every request reads
"No session."

Set `REMOTE_DEV_MODE` for local HTTP work; the cookie then drops `Secure` and
uses `SameSite=Lax`. Production can never take that path by accident — it is
gated on the flag alone, and a test covers both branches.

The test suite runs over `https://testserver` for the same reason, so it
exercises the production cookie path rather than a relaxed one.

## `OWNER ACTION REQUIRED`

1. **A host** for the API — Fly.io, Railway, Render or a small VPS. A monthly
   cost, and a decision I will not make for you.
2. **A domain with TLS.** Also required for passkeys, which bind to a domain
   and cannot be registered against a bare IP.
3. **Set `ZENO_PUBLIC_API_URL`** in Netlify's environment UI to the API
   origin. The build refuses any non-HTTPS value outside localhost.
4. **Provision the owner credential** at the desktop:

```bash
python -c "from reyes_agent.auth import get_owner_auth; print(get_owner_auth().provision('you@example.com','a-long-passphrase-you-choose'))"
```

5. **Register the laptop** from the web app's Devices tab, then run the three
   `setx` lines it prints and restart ZENO.

*What ZENO needs afterward:* nothing else — the connector picks up
`ZENO_GATEWAY_URL`, `ZENO_DEVICE_ID` and `ZENO_DEVICE_TOKEN` from the
environment at startup and dials out on its own.

## Still missing

- **Voice on the remote client.** The microphone button is visibly disabled
  and says why: capture runs on the desktop and has no authenticated remote
  route yet. The QR mic on the LAN is unaffected.
- **Passkeys** — storage and the API exist; registration needs a domain.
- **WebSocket push.** The client polls. Fine at this scale, and a WebSocket
  transport can replace `_claim` without touching anything else.
- **A deployed backend.** Nothing is online.
