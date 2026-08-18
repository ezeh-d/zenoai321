# ZENO — TikTok Setup

## OWNER ACTION REQUIRED

Same boundary as Instagram: ZENO opens the page and gives you the approved
values. You type the password, clear the CAPTCHA and confirm the email or
phone. ZENO does none of those, by design.

```bash
python -c "from reyes_agent.tools import TOOLS; print(TOOLS['social_setup'].func('tiktok'))"
```

## Step 1 — Create the account (you)

https://www.tiktok.com/signup — use the approved Gmail, and the username and
bio `social_setup` prints.

TikTok's minimum age is 13, and account creation may require age
verification. Do not attempt to work around it.

## Step 2 — Developer app (you)

Register at https://developers.tiktok.com/ and create an app.

Products needed:

| product | what it is for |
|---|---|
| **Login Kit** | OAuth |
| **Content Posting API** | publishing |
| **Display API** | reading your own videos and their metrics |

Scopes: `user.info.basic`, `video.publish`, `video.upload`, `video.list`.

**The Content Posting API requires approval, and this is the real wait.**
TikTok reviews the application and asks what the integration does. Answer
honestly: an AI assistant publishing content about its own development, run by
its owner. Expect days, not minutes.

### Unaudited clients post privately

Until the app passes audit, everything it posts is restricted to **SELF_ONLY**
— visible to the account owner. That is TikTok's rule, not a bug, and not
something to route around. It is a good way to test the whole pipeline
end-to-end without anything becoming public.

## Step 3 — OAuth (you)

Authorise:

```
https://www.tiktok.com/v2/auth/authorize/
  ?client_key=CLIENT_KEY
  &scope=user.info.basic,video.publish,video.upload,video.list
  &response_type=code
  &redirect_uri=YOUR_REDIRECT
  &state=RANDOM
```

Exchange the code:

```bash
curl -s -X POST https://open.tiktokapis.com/v2/oauth/token/ \
  -d "client_key=CLIENT_KEY&client_secret=CLIENT_SECRET&code=CODE&grant_type=authorization_code&redirect_uri=YOUR_REDIRECT"
```

You get an access token (24h) and a refresh token (365 days). Store both —
without the refresh token you re-authorise by hand every day.

## Step 4 — Give ZENO the credentials

```bash
python -c "from reyes_agent.security.secrets import manager; manager.set('TIKTOK_ACCESS_TOKEN','PASTE')"
python -c "from reyes_agent.security.secrets import manager; manager.set('TIKTOK_REFRESH_TOKEN','PASTE')"
```

Or in `.env` (never committed):

```
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_ACCESS_TOKEN=
TIKTOK_REFRESH_TOKEN=
```

## Step 5 — Verify

```bash
python -c "from reyes_agent.social.adapters import health; print(health())"
```

## Step 6 — Enable, in dry run

```
ZENO_SOCIAL_ENABLED=true
ZENO_SOCIAL_TIKTOK_ENABLED=true
SOCIAL_DRY_RUN=true
```

## What will bite you

**Publishing is asynchronous.** `POST /v2/post/publish/video/init/` returns a
`publish_id`, not a video. The real state comes from
`/v2/post/publish/status/fetch/`, and only `PUBLISH_COMPLETE` means the video
exists. The adapter polls and will not report success on the init call alone.

**Rate limits are low.** Six requests per minute per user on several
endpoints. The adapter's limiter is set conservatively below TikTok's ceiling.

**Access tokens last 24 hours.** Refresh is not yet automated — the health
surface reports `AUTH_REQUIRED` when the token dies, and refreshing is
currently a manual step. This is a known gap, listed in
`ZENO_SOCIAL_ARCHITECTURE.md`.

**Unaudited apps post SELF_ONLY.** If your first live post is invisible to
everyone else, the app has not passed audit yet. That is expected.
