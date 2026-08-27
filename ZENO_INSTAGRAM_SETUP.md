# ZENO — Instagram Setup (Instagram API with Instagram Login)

This is the **current** Meta API: ZENO logs its own Instagram professional
account in directly and receives an Instagram User access token. There is **no
Facebook Page** and no Basic Display. ZENO never sees or types the Instagram
password — the owner approves in Instagram's own consent screen.

## What ZENO can and cannot do

ZENO **can**: build the authorization URL, exchange the returned code for a
token, validate it, read the professional account, store the token securely,
and publish an owner‑approved post.

ZENO **cannot** (by design): create the account, type the password, clear a
CAPTCHA, or approve the OAuth consent. Those stay with the owner.

## Step 1 — Instagram account is Professional (you)

Settings → **Account type and tools → Switch to professional account →
Creator** (or Business). Content publishing does not work on a personal
account. The ZENO account is **@meetzeno.ai**.

## Step 2 — Meta app with Instagram Login (you)

At https://developers.facebook.com/apps, in your app, add the
**Instagram** product and set it up for **"Instagram API with Instagram
Login"**. Add the two permissions this integration uses:

| permission | for |
|---|---|
| `instagram_business_basic` | read the account identity |
| `instagram_business_content_publish` | create and publish posts/reels |

Messaging and comments permissions are **not** requested here.

Add **@meetzeno.ai** as an Instagram Tester (App roles → Roles) and accept the
invite from the Instagram account, so publishing works while the app is in
development.

## Step 3 — Redirect URI (you)

In the Instagram Login settings, add an **OAuth redirect URI**. For testing
this is your Cloudflare Quick Tunnel host plus the callback path:

```
https://<your-tunnel>.trycloudflare.com/auth/instagram/callback
```

It must match `INSTAGRAM_REDIRECT_URI` (below) **exactly**. Later you can swap
the tunnel for a stable HTTPS URL — change only the config, never code.

## Step 4 — Give ZENO the app credentials

**Never commit these.** `.gitignore` blocks `.env`/`.env.*`; CI fails if an env
file is ever tracked. The App Secret belongs in the OS credential store:

```bash
python -c "from reyes_agent.security.secrets import manager; print(manager.put('INSTAGRAM_APP_SECRET','PASTE_SECRET_HERE'))"
```

The App ID and redirect URI are configuration — put them in `.env`:

```
INSTAGRAM_APP_ID=your-instagram-app-id
INSTAGRAM_REDIRECT_URI=https://<your-tunnel>.trycloudflare.com/auth/instagram/callback
INSTAGRAM_SCOPES=instagram_business_basic,instagram_business_content_publish
INSTAGRAM_API_VERSION=v23.0
INSTAGRAM_CALLBACK_PORT=8765
```

The **access token** and **business account id** are obtained by the OAuth
callback — you do not type them in.

## Step 5 — Start the callback service

The Quick Tunnel forwards to this small, single‑purpose server:

```bash
python -m reyes_agent.social.instagram_callback_server
```

It listens on `127.0.0.1:8765` and only handles `/auth/instagram/callback`.
(It runs separately from ZENO's main app on purpose, so exposing the OAuth
callback to the internet never exposes ZENO's control surface.)

## Step 6 — Connect

Ask ZENO to start the connection, or run the tool directly:

```bash
python -c "from reyes_agent.tools import TOOLS; print(TOOLS['social_connect'].func(action='start'))"
```

Open the returned **authorize_url** in a browser signed in to @meetzeno.ai and
approve. Meta redirects to the callback; ZENO exchanges the code, upgrades to a
60‑day token, validates it, reads the account, and stores the token in the
credential store. The page shows: **Instagram connected: @meetzeno.ai**.

Nothing full is ever logged — only masked status (`Token status: valid`).

## Step 7 — Verify

```bash
python -c "from reyes_agent.tools import TOOLS; print(TOOLS['social_connect'].func(action='status'))"
```

`connected: true` with `username: meetzeno.ai` means ZENO actually reached
Instagram. ZENO can now say **"Instagram connected: @meetzeno.ai."**

## Step 8 — The first test post (only when you ask)

Publishing is gated by `SOCIAL_DRY_RUN`, the kill switch, and an explicit
`owner_approved`. Dry run is ON by default — a full dry run runs without
sending anything. For a **real** first post, host a test image at a public
HTTPS URL, then:

```bash
# Real send: dry run OFF, platform enabled, explicit approval.
ZENO_SOCIAL_INSTAGRAM_ENABLED=true
SOCIAL_DRY_RUN=false
```

```bash
python -c "from reyes_agent.tools import TOOLS; print(TOOLS['social_publish_media'].func(platform='instagram', image_url='https://YOUR-PUBLIC-HOST/zeno-test.jpg', caption='ZENO test post', owner_approved=True))"
```

Or just say: **"ZENO, publish this test post to Instagram."** ZENO reports
`PUBLISHED` only after asking Instagram for the post back by id, and returns the
media/post id. If the API rejects it, ZENO reports the error — it never invents
success.

## What will bite you

- **Media must be a public HTTPS URL.** Instagram fetches the file itself; a
  local Windows path cannot be published. The adapter says so up front.
- **A container is not a post.** Reels are created as a container that must
  reach `FINISHED` before publishing; the adapter polls and refuses to publish
  an unfinished one — the most common way an auto‑publisher silently posts
  nothing.
- **Tokens last ~60 days.** `social_connect action=status` shows the state;
  `instagram_login.refresh_long_lived_token()` renews it.
- **Rate limit:** Meta allows 100 API publishes / 24h; ZENO's limiter stops
  well below that.
