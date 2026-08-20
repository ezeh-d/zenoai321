# ZENO Anywhere v1

## Architecture

The public browser never connects to the Windows machine. The owner PWA sends
an authenticated request to the standalone gateway. The gateway validates the
owner session and browser trust, classifies the action, and writes a bounded
command to its durable queue. The Kernel-managed Windows connector makes an
outbound HTTPS request, claims an allow-listed action, executes it through
ZENO's existing permission/tool/conversation runtime, and reports the real
result.

```text
Owner PWA -> HTTPS gateway -> durable command queue
                                    ^
                                    | outbound HTTPS poll
                                    |
                          ZENO Kernel -> existing tools/brain/memory
```

Owner-state updates use a bounded authenticated SSE invalidation stream with
durable polling fallback. Native Web Push and voice audio are separate,
optional channels. Voice clips are AES-256-GCM encrypted in a size/TTL-bounded
store; only the bound outbound Windows connector can read them.

The gateway imports no desktop automation and exposes no inbound route to the
PC. Local/LAN Phone Companion security remains separate and unchanged.

## Local setup

Use the project virtual environment in PowerShell:

```powershell
.\.venv\Scripts\python.exe tools\zeno_anywhere_admin.py provision-owner --email you@example.com
.\.venv\Scripts\python.exe -m uvicorn reyes_agent.anywhere_gateway:app --host 127.0.0.1 --port 8080
```

For localhost testing set `REMOTE_ACCESS_ENABLED=true` and
`REMOTE_DEV_MODE=true`. Open `http://127.0.0.1:8080/app/`, sign in, and approve
the displayed stable browser ID from the local admin CLI:

```powershell
.\.venv\Scripts\python.exe tools\zeno_anywhere_admin.py list-browsers
.\.venv\Scripts\python.exe tools\zeno_anywhere_admin.py approve-browser <browser-device-id>
```

Register a Windows device in the PWA or with `register-device`, approve it,
then set the one-time values on the Windows machine:

```powershell
setx ZENO_GATEWAY_URL "https://api.example.com"
setx ZENO_DEVICE_ID "<registered-device-id>"
setx ZENO_DEVICE_TOKEN "<one-time-device-token>"
```

Restart ZENO. The connector registers as `zeno-anywhere-connector` under the
existing Kernel and starts after the interface/core runtime. It is stopped by
the Kernel shutdown sequence.

Generate remote-media and Web Push secrets locally (the ignored output file
is never staged):

```powershell
.\.venv\Scripts\python.exe tools\zeno_anywhere_admin.py generate-secrets
```

Set the real owner email in `ZENO_WEB_PUSH_SUBJECT`, then copy the generated
values into the gateway host's encrypted secret manager. Do not commit the
generated file.

## Backend deployment

Run one gateway instance behind an HTTPS reverse proxy:

```text
uvicorn reyes_agent.anywhere_gateway:app --host 0.0.0.0 --port 8080
```

Required configuration (values omitted):

```text
REMOTE_ACCESS_ENABLED=true
REMOTE_DEV_MODE=false
ZENO_PUBLIC_DOMAIN=
ZENO_APP_ORIGIN=
ZENO_API_ORIGIN=
ZENO_OWNER_AUTH_DB=
ZENO_DEVICE_LINK_DB=
ZENO_MEDIA_STORE_DB=
ZENO_MEDIA_ENCRYPTION_KEY=
ZENO_WEB_PUSH_DB=
ZENO_WEB_PUSH_PUBLIC_KEY=
ZENO_WEB_PUSH_PRIVATE_KEY=
ZENO_WEB_PUSH_SUBJECT=
ZENO_WEB_PUSH_ENCRYPTION_KEY=
WEB_CONCURRENCY=1
```

The database paths must use persistent encrypted-at-rest storage and regular
backups. v1 is intentionally single-instance because SQLite is the queue and
auth transaction authority. Multi-instance deployment requires a shared
transactional database first.

## Netlify frontend

```powershell
npm.cmd install
$env:ZENO_PUBLIC_API_URL="https://api.example.com"
npm.cmd run build
npm.cmd test
```

Deploy the repository with `netlify.toml`; publish directory is `web`. The
build copies the audited FastAPI owner shell into `web/app`, emits only the
public API origin, validates HTTPS, generates exact `connect-src` headers, and
contains no API key or connector token.

### Terminal-independent Windows fallback

When no permanent gateway host or named Cloudflare tunnel is available, the
Windows supervisor can keep the local PWA plus an account-less quick tunnel
running after every owner logon. It is a fallback, not a production gateway:

```powershell
.\.venv\Scripts\python.exe tools\zeno_anywhere_startup.py install
.\.venv\Scripts\python.exe tools\zeno_anywhere_startup.py status
.\.venv\Scripts\python.exe -m reyes_agent.remote_access.anywhere status
```

The hidden scheduled task owns one supervisor instance and restarts it on
failure. The supervisor owns bounded server/tunnel children, verifies the
public `/app` path before reporting `ONLINE`, and publishes the verified URL
every 30 seconds. The Netlify rendezvous expires it after 90 seconds, so a
dead PC cannot leave a stale launcher target indefinitely. The launcher also
checks freshness and accepts only `https://*.trycloudflare.com` addresses.

Configure the same long random `ZENO_ANYWHERE_SECRET` in the owner's Windows
secret store/environment and in Netlify's environment UI. Set
`ZENO_ANYWHERE_ENTRY=https://zenoai321.netlify.app` on Windows. The secret is
used only to authenticate rendezvous writes and is never returned to the
browser or written into Task Scheduler.

This mode needs no Claude, Codex, VS Code, CMD, or PowerShell process after
installation. It still requires the owner to be logged into Windows, the PC
to be awake, outbound Cloudflare connectivity, and a deployed Netlify build.
Account-less Quick Tunnels have no uptime guarantee and their changing origin
is unsuitable for durable passkeys/cookies. A stable cloud gateway or named
tunnel remains the production architecture.

## Container deployment

`Dockerfile.anywhere` contains only the cloud gateway dependencies and runs as
a non-root user with one Uvicorn worker. `render.yaml` provisions one
persistent volume and keeps secrets out of source control. The `/ready`
endpoint fails closed when production origins, persistent paths, owner setup,
or the single-worker SQLite contract are invalid.

```powershell
docker build -f Dockerfile.anywhere -t zeno-anywhere .
```

Do not increase the worker/replica count while SQLite is authoritative.
Horizontal scale still requires transactional PostgreSQL repositories,
distributed rate limiting and shared pub/sub.

## Built and verified

- scrypt owner password, rate limiting, lockout and nonce replay protection;
- short HttpOnly sessions, rotating refresh cookies, CSRF and revocation;
- real WebAuthn/passkey registration and login with user verification;
- pending/approved/blocked/revoked browser and Windows-device states;
- allow-listed structured commands, nested secret rejection and idempotency;
- offline queue, explicit expiry, cancellation, acknowledgement and result;
- sensitive-command approval inbox and emergency remote kill switch;
- redacted audit/activity history;
- managed outbound connector with TLS enforcement and bounded backoff;
- same ZENO conversation/history/task/memory/tool path on Windows;
- installable responsive PWA with offline shell and update-safe cache version;
- authenticated bounded realtime updates with durable polling recovery;
- user-initiated 15-second remote voice turns with echo/noise processing,
  encrypted bounded media, desktop STT/policy/brain/TTS and phone playback;
- no false biometric claim: browser trust and speaker verification remain
  separate, and remote voice cannot perform control/financial actions;
- native opt-in Web Push with encrypted subscriptions, allow-listed public
  providers, generic lock-screen-safe messages and dead-subscription cleanup;
- real allow-listed graceful app closing and saved approved workflow replay;
- exact-origin credentialed CORS, secure cookies and security headers.

## Honest operating limits

- Remote voice is bounded push-to-talk, not an always-open cloud microphone.
  Always-on wake listening remains local to the PC/LAN privacy boundary.
- Voice requests are read/conversation-only because the gateway cannot safely
  classify opaque audio before upload. Use typed commands plus the approval
  inbox for desktop control.
- SQLite deliberately permits one gateway worker/replica. The readiness check
  rejects a multi-worker configuration instead of pretending it is safe.
- A real production hostname, TLS, Render/cloud account, physical phone PWA
  install, microphone permission and passkey ceremony require the owner's
  actual domain/device/hosting credentials and cannot be simulated by tests.
- The scheduled quick-tunnel fallback is self-healing but not permanently
  address-stable. Netlify deployment and its environment secret require an
  authenticated owner Netlify session; source code cannot supply that access.
