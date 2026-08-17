# ZENO — Security Review

## Automated scan

443 modules parsed:

| check | result |
|---|---|
| Hardcoded API keys / tokens (`sk-`, `AIza`, `xox*`) | **none** |
| Duplicate tool registrations | **none** |
| Bare `except:` swallowing `KeyboardInterrupt` | **none** |
| Non-daemon threads | 2 found — **fixed** |

Credentials live in `.env`, which is gitignored — verified when a commit
attempt correctly refused to stage it.

## Phone authority — the significant change this session

A locally-paired phone previously carried `remote_audio_send` alone. That made
the remote microphone useless: every sentence was transcribed at 97% confidence
and then refused with *"this device does not have the 'status' scope"*. ZENO
could hear the owner and was not permitted to answer him.

**Widened deliberately** to the same scopes a passkey-verified device holds. The
reasoning: the owner's voice through his own phone is the owner speaking; the
phone is a conduit, not a lesser principal.

**What did not widen, and cannot.** Money movement and security/credential
changes are refused by **category** in `remote_access/policy.py`, *before scopes
are consulted*. No grant reaches them.

Verified on the real policy:

```
ALLOW   what time is it
ALLOW   open slack and send good night to general
ALLOW   who are your agents

BLOCK   transfer 500 to my brother
BLOCK   change my password
BLOCK   disable the firewall
BLOCK   show me my api key
```

A test pins both halves.

## Two-tier pairing

Added a **guest key** that pairs a listen-only microphone. It is a separate
standing key rather than a flag, so the grant belongs to the *code* and not to
the request presenting it — there is no parameter the page could change to
widen it. Verified: the guest code cannot open an app, send a message, or ask
the time.

## Standing key

Never expires, and is constrained instead of time-boxed:

- buys **one** permission on the guest key, audio only
- **refused from any address that is not this machine's own local network** —
  a photographed QR is useless to someone not already on the owner's Wi-Fi
- rotatable in one call, killing every printed code
- the session still expires; the phone re-pairs silently from the key it holds

Stored in plaintext because a QR must be regeneratable — the same reason Windows
keeps a Wi-Fi password rather than its hash. It lives in `LOCALAPPDATA` under
the owner's account.

## Code display

`presentation/evidence.py` can show source to a visitor. `.env`, `secrets.*`,
`credentials.*`, `*.pem`, `*.key` and `id_rsa*` are refused **by name before any
read**, and any key-shaped assignment is redacted even inside an allowed file.
Asking for an API key returns a refusal, not a redaction that might slip.

## Loopback-only surfaces

The network map, QR generation and mode changes are loopback-only — verified
**403 from 192.168.1.117**. A paired phone does not need the laptop's address map.

## Owner approval preserved

Serious mode changes how ZENO reasons and speaks, never what he may do. Tests
evaluate the real policy in both modes; money, passwords and firewall stay
refused in each.

## Cleanup performed

Every verification harness I ran this session had paired itself as a **trusted
device** — "Proof harness", "Frame reader", "Chain reader", "Level meter". The
scope widening reached all of them. They are revoked; only real phones remain.

Worth stating plainly: that mess was mine, and a reader of the device list
should know why unfamiliar names once appeared in it.

## Not reviewed

- Browser automation permission surface
- Opportunity engine (no financial execution path was found, but it was not audited)
- Shell/command-injection paths in the coding subsystem
