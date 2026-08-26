# Moving ZENO to another laptop

ZENO is built to move. Three things travel differently — don't mix them up:

| Layer | Travels via | Notes |
|---|---|---|
| **Code** | `git clone` | Everything in this repo. |
| **State** (knowledge vault, spatial memory, vocabulary, voice, models) | `migrate export` → `migrate import` | Lives OUTSIDE git; ~158 MB here. |
| **Secrets** (`.env`, owner auth, device/tunnel/phone/social tokens) | **You, by hand, over a secure channel** | ZENO refuses to put these in an export bundle. |
| **Rebuildables** (`.venv`, `node_modules`, browser cache) | Recreated on the new machine | Never copy. |

## See exactly what will move

```bash
python -m reyes_agent.migrate
```

Prints an inventory (EXPORT / opt-in / BY HAND / rebuild) and the checklist below.

## The move

**On the OLD laptop**
```bash
python -m reyes_agent.migrate export        # writes zeno-profile-<host>.zip (secret-free)
```
Add `--include-biometrics` only if you want your voice profile to travel too.

**Carry across (securely, yourself):** the bundle, and your secrets — `.env` and the
owner-auth / ZENO-Anywhere / phone / social token stores shown as **BY HAND**.

**On the NEW laptop**
```bash
git clone <repo> && cd REYES
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
npm install
python -m reyes_agent.migrate import zeno-profile-<host>.zip          # dry run: shows the plan
python -m reyes_agent.migrate import zeno-profile-<host>.zip --apply  # actually restore
```
Then place your `.env`, and:
```bash
python -m reyes_agent.auth.provision      # fresh owner auth on the new device
```
Re-pair ZENO Anywhere / the phone (device tokens are per-machine — re-issued, not copied).
First run re-downloads model caches (embeddings, voices) as needed.

## Why secrets aren't in the bundle

A profile bundle is easy to email or drop in cloud storage. If it carried your API
keys or auth material, one careless copy would leak them. The export is verified in
tests to contain **no secret paths and no secret values** — so the bundle is safe to
move over ordinary channels, and only the small set of secrets needs the careful path.
