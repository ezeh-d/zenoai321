# ZENO — Online Access Security Review

Scope: everything added to put ZENO on the internet — owner authentication,
the command queue, the outbound connector, and the web client.

## The items the brief listed

| check | result |
|---|---|
| exposed API keys | none — `grep` for assigned literals across all four new modules returns nothing |
| frontend secrets | none — asserted by a test that scans the served bundle for `key/secret/token/password` assigned to a literal |
| command injection | **not reachable** — see below |
| arbitrary shell execution | **no path exists** — no `subprocess`, `os.system`, `eval`, `exec` or `shell=True` anywhere in the remote path |
| path traversal | the only path-shaped route is `/app/icon-{size}.png`, and `size` must be exactly `"192"` or `"512"` before it touches the filesystem |
| insecure CORS | explicit allow-list from `domains.allowed_origins()`, **empty until a domain is configured**; never a wildcard; `allow_credentials=True` |
| unauthenticated API endpoints | 11 by design, each justified below |
| broken authorization | two independent identities; a device token cannot read owner data, an owner session cannot claim a device queue |
| replay attacks | login requires a fresh ≥16-char nonce, single-use; refresh tokens rotate on use |
| leaked logs | audit entries pass through `_scrub()`, which redacts any key containing password/token/secret/csrf/refresh/session/key/credential/otp/code |
| hardcoded passwords | none |
| accidental public Windows services | **nothing listens** — the desktop dials out only |
| unsafe file operations | the remote path performs none |

## Why command injection is not reachable

The browser never sends a command. It sends an **action name**, and that name
must appear in `REGISTERED_ACTIONS`. Anything else is rejected with 400
before it reaches a queue — `test_an_unregistered_action_is_refused_before_it_reaches_a_queue`
sends `run_shell` and asserts the 400.

The desktop then maps that action to a registered **ZENO tool** and builds the
arguments with a per-action function. A payload cannot introduce a parameter
the builder does not pass. Application names are additionally allow-listed.

There is no string from the network that becomes a command line, a module
name, or a filesystem path.

## The 11 unauthenticated routes, and why

**`/auth/status`, `/auth/login`, `/auth/refresh`, `/auth/logout`,
`/auth/session`, `/auth/passkey/options`, `/auth/passkey/complete`** — these
must work before a session exists. `/auth/status` reveals only whether setup
has been done, which the login page needs in order to render at all.

**`/device/heartbeat`, `/device/claim`, `/device/ack`, `/device/complete`** —
these carry no owner session because the caller is a *machine*. Every one of
them authenticates a device token in its handler, verified mechanically:

```
OK  post("/device/heartbeat")
OK  post("/device/claim")
OK  post("/device/ack")
OK  post("/device/complete")
```

`test_a_device_cannot_claim_with_a_bad_token` asserts the 401.

Everything else is registered on a router carrying
`dependencies=[Depends(require_owner)]`, so a route added later **without its
own decorator is still protected**. Forgetting the decorator is the classic
way an unauthenticated endpoint ships; this makes forgetting safe.

## Layers a stolen password still has to pass

1. **Lockout** — 5 failures, 15 minutes, per identity.
2. **Rate limit** — the `login` bucket, 8 per 5 minutes.
3. **Browser approval** — a new browser is `PENDING`; protected routes answer
   403 until the owner approves it *at the desktop*. A stolen password on an
   unknown browser gets a session and nothing else.
4. **Command approval** — `open_app` lands in `PENDING_APPROVAL`. A
   connected, approved laptop polling the queue receives **nothing** until the
   owner decides.
5. **Category refusal** — FINANCIAL and SENSITIVE are refused remotely
   outright, regardless of session, approval or scope.

## Cookies

`HttpOnly; Secure; SameSite=None`. The session token is **not** in the JSON
response body and **not** in `localStorage`, so injected script cannot read
it. Only the CSRF token is script-readable — required, since it travels as a
header, and useless without the cookie.

The frontend was originally written to read tokens from the body and store
them in `localStorage`. That was wrong and has been corrected; the client now
sends `credentials:"include"` and holds no session token at all.

## A real operational trap, documented rather than patched over

Because the cookie is `Secure`, a browser on `http://localhost` **silently
drops it** and every request reads "No session." This cost real debugging
time here: the test suite failed with 401s that looked like an auth bug and
were a transport rule.

`REMOTE_DEV_MODE` relaxes it for local work, and production cannot take that
branch by accident. The suite runs over `https://testserver` so it exercises
the production cookie path rather than the relaxed one.

## What I did not verify

- **No penetration testing.** No fuzzing, no active attempt to break the
  session logic beyond the negative tests written here.
- **No TLS configuration reviewed**, because nothing is deployed.
- **Passkey verification is unexercised** — storage and endpoints exist, but
  no registration has been performed against a real domain.
- **The scrypt cost (348 ms) was measured on this machine only.** On a slower
  host it will be slower; on a much faster one, cheaper to attack.
- **CORS has never been exercised cross-origin**, because there is no second
  origin yet. The allow-list is empty and therefore cannot be wrong yet.

## Residual risk, plainly

The largest remaining risk is not in this code: it is that **the owner
password is the only thing standing in front of a machine that can open
applications and read files**, and passkeys — the fix — need a domain that
does not exist yet.

Until then the browser-approval gate is what makes a leaked password
survivable, and it only works if the owner does not approve browsers they do
not recognise.
