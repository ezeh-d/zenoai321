# ZENO Deployment

## What is proven to work

The full chain was run end to end on 2026-08-18:

```
phone / any browser
   ↓ HTTPS (public internet)
cloudflared quick tunnel        https://<random>.trycloudflare.com
   ↓ outbound only — no port is opened on the Windows machine
anywhere gateway                127.0.0.1:8090
   ↓
PWA + owner API
```

Measured, not assumed:

| request | result |
|---|---|
| `GET /health` over public HTTPS | `200` `{"state":"ONLINE"}` |
| `GET /app` | `200` |
| `GET /app/manifest.webmanifest` | `200` |
| `GET /app/sw.js` | `200` |
| `GET /app/icon-192.png` | `200` |
| `GET /nonexistent` | `404` — so the 200s are real, not a catch-all |
| `GET /ready` | `503`, listing exactly what production still needs |

That `503` is the system working. `/ready` refuses to claim readiness until
persistent storage paths, a public domain and an HTTPS owner origin are set.

## Installed on this machine

| tool | version | state |
|---|---|---|
| `cloudflared` | 2026.7.3 | **working** — the HTTPS origin above |
| `netlify-cli` | 27.1.2 | installed; deploy needs your login |
| Docker Desktop | 4.87.0 (CLI 29.7.2) | installed; **engine cannot start** — see below |
| `faster-whisper` model | `Systran/faster-whisper-base` | working, ~100 languages |
| VAPID keypair | generated locally | Web Push reports `configured: True` |

## Netlify

Netlify serves **static files only**. It hosts the PWA shell; it cannot host
the FastAPI gateway. So the split is:

- **frontend** → Netlify, a stable `https://<name>.netlify.app`
- **API** → the gateway, reached over cloudflared (or a container host)

### Build

```bash
ZENO_PUBLIC_API_URL="https://your-api-origin" node scripts/build-config.js
```

This copies `reyes_agent/static/app.html` and its assets into `web/app/`,
writes `web/zeno-config.js`, and generates `web/_headers` with a CSP whose
`connect-src` is scoped to exactly that API origin. It **refuses to build** if
the API URL is not HTTPS outside localhost, and refuses if a secret-shaped
name appears in the public list.

### Deploy

`netlify login` opens a browser for OAuth — that is yours to do, not ZENO's.

```bash
netlify login
```

```bash
netlify deploy --prod --dir=web
```

Then set `ZENO_PUBLIC_API_URL` in Netlify's environment UI so their build
matches. Nothing secret goes there: everything in `zeno-config.js` reaches the
browser and is public by definition.

For the account-less quick-tunnel fallback, the stable launcher now discovers
the currently verified tunnel through `/api/endpoint`; it no longer needs a
new static deploy for every tunnel URL. That function stores only the URL and
timestamp. Writes require `ZENO_ANYWHERE_SECRET`, which must be configured in
Netlify's environment and in the owner's local Windows secret store. The
launcher rejects stale records and non-`trycloudflare.com` addresses.

### After the site exists

```
ZENO_PUBLIC_DOMAIN=<name>.netlify.app
ZENO_APP_ORIGIN=https://<name>.netlify.app
```

The gateway's CORS allow-list is **empty until these are set**, so it is
fail-closed rather than fail-open.

## The tunnel

```bash
cloudflared tunnel --url http://127.0.0.1:8090
```

**Outbound only.** The Windows machine opens no inbound port; cloudflared
dials Cloudflare and holds the connection. That is the same property the
desktop device connector relies on.

**A quick-tunnel URL changes every restart.** The rendezvous/launcher follows
that change automatically after it is deployed, but this is still a testing
fallback: Cloudflare provides no uptime guarantee, browser-origin state changes
with the URL, and passkeys require a stable origin. A named tunnel or hosted
gateway is the production answer.

Install the independent Windows supervisor with:

```powershell
.\.venv\Scripts\python.exe tools\zeno_anywhere_startup.py install
```

It starts at owner logon, runs hidden under Task Scheduler, prevents duplicate
instances, restarts failed children with bounded backoff, and reports `ONLINE`
only after a real public `/app` request succeeds. No IDE or terminal needs to
remain open.

## `OWNER ACTION REQUIRED` — Docker

Docker Desktop **4.87.0 is installed** and the CLI works
(`docker --version` → 29.7.2). The engine will not start:

```
request returned 500 Internal Server Error for API route and version
.../dockerDesktopLinuxEngine/v1.55/info
```

The cause: **WSL has no distribution installed**, and Docker Desktop's Linux
engine needs one. `wsl -l -v` prints the usage text, which is what WSL does
when nothing is installed.

Fixing it needs administrator rights and a reboot, which I do not have and
will not attempt to obtain. In an **elevated** PowerShell:

```powershell
wsl --install
```

Reboot, then start Docker Desktop and check:

```bash
docker info
```

Once the engine runs, the image builds with:

```bash
docker build -f Dockerfile.anywhere -t zeno-anywhere .
```

### `.dockerignore` — added

There was none. The build context is uploaded to the daemon **in full, before
any COPY runs**, so `.env`, `.venv`, `.git` and every local database were
being sent even though `Dockerfile.anywhere` only copies `reyes_agent`.

The Dockerfile's narrow `COPY` was doing the right thing, but it was the only
thing standing between a future `COPY . .` and a secret in a published image.
Now there are two locks.

## What still has no answer

- **A permanent API origin.** The quick tunnel is ephemeral and Netlify cannot
  host the gateway. A named Cloudflare tunnel, or a container host once Docker
  runs, is the real fix.
- **Web Push delivery is untested.** Keys are installed and the service
  reports `ready`, but no browser has subscribed and no notification has been
  delivered. It is configured, not proven.
- **Passkeys need a stable domain.** They bind to an origin, so a rotating
  tunnel URL cannot register one.
