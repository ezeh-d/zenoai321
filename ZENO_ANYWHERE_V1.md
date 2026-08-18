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
- exact-origin credentialed CORS, secure cookies and security headers.

## Honest v1 limits

- Internet microphone streaming is not built; the Voice screen is disabled.
  Local/LAN phone microphone and desktop voice remain available.
- Push delivery is not built; the notification screen says so. Approvals and
  command events are available in their real in-app screens.
- `close_app` and `run_automation` can enter approval state but have no remote
  executor; they fail rather than being mapped to an unsafe/fake action.
- The transport uses bounded polling rather than WebSockets. Status and result
  continuity are real, but push latency follows the polling interval.
- Netlify hosts only static frontend files. The Python gateway requires a
  separate persistent HTTPS host; it must not run as an ephemeral function.
