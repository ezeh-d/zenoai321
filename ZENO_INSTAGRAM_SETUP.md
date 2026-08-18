# ZENO — Instagram Setup

## OWNER ACTION REQUIRED

ZENO cannot complete this. Not "has not yet" — **cannot**, and the parts it
cannot do are the parts that protect the account.

Creating an Instagram account requires entering a password, clearing a
CAPTCHA, and confirming an email and usually a phone number. ZENO does not
type credentials, does not answer CAPTCHAs and does not enter verification
codes. There is no tool in the codebase that does, deliberately — a test
(`test_setup_tool_never_offers_to_type_credentials`) asserts `social_setup`
never offers to.

What ZENO does instead: `social_setup` opens the official page and hands you
the exact approved values to type.

```bash
python -c "from reyes_agent.tools import TOOLS; print(TOOLS['social_setup'].func('instagram'))"
```

## Step 1 — Create the account (you)

Go to https://www.instagram.com/accounts/emailsignup/ and register with the
Gmail you have approved for ZENO. Use the username, display name and bio that
`social_setup` prints, so the identity stays consistent with `identity.py`.

## Step 2 — Switch to Professional (you)

**Settings → Account type and tools → Switch to professional account →
Creator.**

This is required. The Graph API will not publish to, or report insights for, a
personal account. Do not enter business details that are not true — pick
Creator, which is what ZENO actually is.

## Step 3 — Link a Facebook Page (you)

Instagram's publishing API is reached through a Facebook Page. Create one at
https://www.facebook.com/pages/create, then link it under
**Settings → Sharing to other apps → Facebook.**

## Step 4 — Create a Meta app (you)

At https://developers.facebook.com/apps → **Create app** → *Business*.

Add the **Instagram Graph API** product and request these permissions:

| permission | what it is for |
|---|---|
| `instagram_basic` | read the account |
| `instagram_content_publish` | publish posts and Reels |
| `instagram_manage_insights` | read analytics |

Publishing permissions need **App Review** for a live app. In Development
mode they work for accounts with a role on the app, which is enough for ZENO's
own account.

## Step 5 — Get a long-lived token (you)

Short-lived tokens expire in an hour. Exchange for a 60-day token:

```bash
curl -s "https://graph.facebook.com/v21.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APP_ID&client_secret=APP_SECRET&fb_exchange_token=SHORT_TOKEN"
```

Then find the Instagram business account id:

```bash
curl -s "https://graph.facebook.com/v21.0/me/accounts?access_token=LONG_TOKEN"
curl -s "https://graph.facebook.com/v21.0/PAGE_ID?fields=instagram_business_account&access_token=LONG_TOKEN"
```

## Step 6 — Give ZENO the credentials

**Never commit these.** `.gitignore` blocks `.env` and `.env.*`, CI fails the
build if an environment file is ever tracked, and gitleaks scans full history.

Preferred — Windows Credential Manager, so the token never sits in a file:

```bash
python -c "from reyes_agent.security.secrets import manager; manager.set('INSTAGRAM_ACCESS_TOKEN','PASTE_HERE')"
```

Or in `.env` (read only if keyring has nothing):

```
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_BUSINESS_ACCOUNT_ID=
```

## Step 7 — Verify

```bash
python -c "from reyes_agent.social.adapters import health; print(health())"
```

`NOT_CONFIGURED` names the missing variable. `AUTH_REQUIRED` means the token
was rejected — it expired, or the account is not Professional. `HEALTHY`
shows the username and follower count, which means ZENO actually reached
Instagram.

## Step 8 — Enable, still in dry run

```
ZENO_SOCIAL_ENABLED=true
ZENO_SOCIAL_INSTAGRAM_ENABLED=true
SOCIAL_DRY_RUN=true
```

Prepare a post and read the approval card. Nothing is sent while dry run is
on — that is asserted by a test, not just intended.

## Step 9 — The first live post

Set `SOCIAL_DRY_RUN=false` only when you have read an approval card and want
that exact post to go out. Mode stays `APPROVAL`.

## What will bite you

**Media must be at a public HTTPS URL.** The Graph API fetches the file
itself; it does not accept an upload from ZENO's process. A local path cannot
be published, and the adapter says so rather than letting Meta return a
confusing 400.

**A container is not a post.** Reels are created as a container, which must
reach `FINISHED` before publishing. The adapter polls for up to 180s and
refuses to publish an unfinished container. This is the most common way an
automated Instagram publisher silently produces nothing.

**25 posts per 24 hours** is Meta's limit. ZENO's limiter stops at 20.

**Tokens expire every 60 days.** `auth_state()` records `INVALID` and the
health surface reports `AUTH_REQUIRED`. Nothing auto-renews — that is your
step.
