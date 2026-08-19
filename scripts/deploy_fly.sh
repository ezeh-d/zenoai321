#!/usr/bin/env bash
# Deploy the ZENO Anywhere gateway to Fly.io.
#
# WHAT THIS DOES, AND WHAT IT LEAVES TO YOU
# -----------------------------------------
# It pushes SECRETS with `fly secrets set` (which stores them encrypted in Fly,
# never in git or the image) and then deploys. It does NOT create your Fly
# account, log you in, or make the paid-plan decision -- those are yours, and
# the script stops with a clear message if they are not done.
#
# Run it from the repo root:
#   bash scripts/deploy_fly.sh
#
# Re-running is safe: `fly secrets set` updates in place, and `fly deploy`
# rolls out a new release with automatic rollback on a failed health check.
set -euo pipefail

cd "$(dirname "$0")/.."

say()  { printf '\n\033[36m%s\033[0m\n' "$*"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$*"; exit 1; }

command -v fly >/dev/null 2>&1 || command -v flyctl >/dev/null 2>&1 \
  || fail "flyctl is not installed. Install it, then re-run:
  Windows: iwr https://fly.io/install.ps1 -useb | iex
  macOS/Linux: curl -L https://fly.io/install.sh | sh"
FLY="$(command -v fly || command -v flyctl)"

say "1. Checking you are signed in to Fly"
"$FLY" auth whoami >/dev/null 2>&1 \
  || fail "You are not signed in. Run:  fly auth login   (or: fly auth signup)
This needs YOUR Fly account and a payment method on file -- that decision is
yours to make, so the script stops here."
echo "   signed in as $("$FLY" auth whoami 2>/dev/null)"

# --- app + volume ------------------------------------------------------
APP="$(grep -E '^app\s*=' fly.toml | head -1 | sed -E 's/.*"(.*)".*/\1/')"
say "2. App: $APP"
if ! "$FLY" status -a "$APP" >/dev/null 2>&1; then
  echo "   this app does not exist yet."
  fail "Run 'fly launch --no-deploy --copy-config' once to create it (it will
let you pick a unique name and a region), then re-run this script. Launching
interactively is left to you so you can choose the name and confirm the plan."
fi

REGION="$(grep -E '^primary_region' fly.toml | sed -E 's/.*"(.*)".*/\1/')"
if ! "$FLY" volumes list -a "$APP" 2>/dev/null | grep -q zeno_data; then
  say "3. Creating the persistent volume (1GB) -- SQLite lives here"
  "$FLY" volumes create zeno_data --region "$REGION" --size 1 --yes -a "$APP"
else
  echo "3. Volume zeno_data already exists"
fi

# --- secrets -----------------------------------------------------------
# Read from .env if present. Nothing here is echoed.
say "4. Setting secrets (encrypted in Fly; never printed, never committed)"
[ -f .env ] && set -a && . ./.env && set +a || true

need_domain="${ZENO_PUBLIC_DOMAIN:-}"
[ -n "$need_domain" ] || fail "ZENO_PUBLIC_DOMAIN is not set. Put your domain
(e.g. zeno-yourname.netlify.app, or a custom domain) in .env first -- the owner
API needs it for cookies and CORS."

secrets=()
add() { [ -n "${2:-}" ] && secrets+=("$1=$2") || echo "   (skipped $1 -- not set in .env)"; }

add ZENO_PUBLIC_DOMAIN        "${ZENO_PUBLIC_DOMAIN:-}"
add ZENO_OWNER_ORIGINS        "${ZENO_OWNER_ORIGINS:-https://$need_domain}"
add ZENO_MEDIA_ENCRYPTION_KEY "${ZENO_MEDIA_ENCRYPTION_KEY:-}"
add ZENO_WEB_PUSH_PUBLIC_KEY  "${ZENO_WEB_PUSH_PUBLIC_KEY:-}"
add ZENO_WEB_PUSH_PRIVATE_KEY "${ZENO_WEB_PUSH_PRIVATE_KEY:-}"
add ZENO_WEB_PUSH_SUBJECT     "${ZENO_WEB_PUSH_SUBJECT:-}"
add GOOGLE_OAUTH_CLIENT_ID    "${GOOGLE_OAUTH_CLIENT_ID:-}"
add GOOGLE_OAUTH_CLIENT_SECRET "${GOOGLE_OAUTH_CLIENT_SECRET:-}"

if [ "${#secrets[@]}" -gt 0 ]; then
  "$FLY" secrets set --stage -a "$APP" "${secrets[@]}"
  echo "   staged ${#secrets[@]} secret(s) -- they apply on the next deploy"
fi

# --- deploy ------------------------------------------------------------
say "5. Deploying"
"$FLY" deploy -a "$APP" --ha=false --strategy immediate

# --- verify: it is not deployed until it ANSWERS -----------------------
say "6. Verifying the release actually serves"
host="$("$FLY" status -a "$APP" --json 2>/dev/null | grep -oE '"Hostname":\s*"[^"]+"' | head -1 | sed -E 's/.*"([^"]+)"$/\1/')"
host="${host:-$APP.fly.dev}"
url="https://$host"
echo "   $url"

ok=0
for i in $(seq 1 20); do
  sleep 6
  state="$(curl -fsS --max-time 8 "$url/health" 2>/dev/null | grep -oE '"state":\s*"[^"]+"' || true)"
  if echo "$state" | grep -q ONLINE; then echo "   /health -> $state"; ok=1; break; fi
  echo "   ...waiting ($((i*6))s)"
done
[ "$ok" = 1 ] || fail "The machine deployed but /health did not report ONLINE.
Check:  fly logs -a $APP"

ready_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$url/ready" || true)"
say "Deployed. /health is ONLINE."
if [ "$ready_code" = "200" ]; then
  echo "/ready is 200 -- the gateway is fully live."
else
  echo "/ready is $ready_code -- expected until you provision the owner:"
  echo "  fly ssh console -a $APP -C \"python -m reyes_agent.remote_access.provision_owner\""
  echo "Then point your web app (Netlify) at:  $url"
fi
