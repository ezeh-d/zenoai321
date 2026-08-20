# Codex / Claude coordination

Two agents work in this repo. This file keeps them out of each other's way.

## CLAUDE OWNS — ZENO Anywhere (remote reachability)

Everything that makes ZENO reachable from a phone/browser, securely:

| area | files |
|---|---|
| supervisor / persistence / recovery | `reyes_agent/remote_access/anywhere.py` |
| tunnel gateway | `reyes_agent/remote_access/tunnel.py` |
| Netlify rendezvous (PC side) | `reyes_agent/remote_access/rendezvous.py` |
| Netlify rendezvous (function) | `netlify/functions/endpoint.mjs` |
| Netlify launcher + build | `web/index.html`, `netlify.toml`, `package.json`, `scripts/build-config.js` |
| authenticated remote API | `reyes_agent/remote_access/cloud_api.py` |
| fail-closed boundary | `reyes_agent/remote_access/boundary.py` |
| owner auth / trusted devices | `reyes_agent/auth/owner.py`, `reyes_agent/auth/provision.py` |
| device link / command queue | `reyes_agent/remote_access/device_link.py` |
| desktop agent | `reyes_agent/remote_access/desktop_agent.py` |

Owner-facing entry point: **https://zenoai321.netlify.app** (Netlify site
`zenoai321`, account `owntred399`).

## CODEX OWNS — ZENO evolution

- GitHub research for improvements
- core stability, performance, architecture research
- agent and memory improvements
- general ZENO evolution

## SHARED FILES — touch with care

Both sessions may need these. Edit the smallest section; preserve the other's
changes; review the diff.

- `reyes_agent/config.py` — config for every subsystem
- `reyes_agent/web.py` — the FastAPI app both remote and core routes live on
- `reyes_agent/tools/__init__.py` — the tool registry
- `.env.example`, `.gitignore`
- `reyes_agent/agent.py` — the shared turn loop

## OBSERVED CO-DEVELOPMENT

The ZENO Anywhere files above (`anywhere.py`, `rendezvous.py`,
`endpoint.mjs`, `web/index.html`) have been edited by BOTH sessions this
cycle. The changes have been complementary and are kept: timing-safe secret
comparison and a 90s staleness window in the rendezvous function, a matching
`PUBLISH_EVERY_S=30s` refresh and `reap_failure` in the supervisor. If you are
Codex and these are yours: they are good, they are kept, and Claude built the
persistence/recovery/auto-start around them. Please leave ZENO Anywhere to
Claude from here to avoid two hands on the same wheel.

## POTENTIAL CONFLICTS

- **`web.py` startup** — Claude's supervisor spawns `uvicorn reyes_agent.web:app`
  on port 8768. If Codex changes app startup, the remote server inherits it.
- **`config.PHONE_COMPANION_PORT` (8768)** — the whole remote chain assumes it.
  Do not change without telling Claude.
- **`boundary._PUBLIC_REMOTE_PREFIXES`** — the allow-list that decides what a
  tunnelled request may reach. Claude owns it; a careless addition here is a
  remote-exposure bug.

## NON-DESTRUCTIVE GIT

Neither session runs `git reset --hard`, `git clean -fd`, forced checkout, or
forced push. Uncommitted work in `presentation/*.json` belongs to the other
session and is left untouched.
