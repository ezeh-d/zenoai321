"""Turning a chosen route into something the phone can scan.

This is the join between two things that were already separate and correct:
`routes.py` knows WHERE the phone can reach ZENO, and `phone_security.py`
knows HOW it proves it is allowed to. Neither needed changing to support a
second network -- an address and a token are independent, which is the whole
reason both networks can share one pairing system.

    "QR tokens remain short-lived and single-use."

They are, and this does not weaken that: the token comes from
`create_pair()` exactly as the Wi-Fi path always did. A hotspot QR is not a
lesser credential, it is the same credential printed with a different host.

WHAT REGENERATING A QR DOES TO THE OTHER ONE
--------------------------------------------
`create_pair()` cancels any unconsumed pair, so asking for a hotspot QR does
invalidate an outstanding Wi-Fi QR. That is a property of the token, not of
the route, and it is the safe direction: at most one pairing code is live at
a time. Both remain REGENERATABLE on demand, which is what the owner asked
for -- neither configuration is destroyed, and either can be reissued in a
second.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from reyes_agent.remote_mic import pairing, routes


def offer(mode: str = "", *, with_qr: bool = True) -> dict[str, Any]:
    """A scannable pairing offer for the requested network.

    `mode` is AUTO, LAN_WIFI or LAPTOP_HOTSPOT. An explicit mode that is not
    available comes back as a refusal naming what IS available, rather than
    quietly returning the other network -- being handed a Wi-Fi QR after
    asking for the hotspot is how an owner ends up scanning a code that
    cannot work from where they are standing.
    """
    from reyes_agent import config
    from reyes_agent.phone_security import get_phone_security

    wanted = (mode or "").strip().upper() or getattr(
        config, "REMOTE_MIC_NETWORK_MODE", routes.AUTO)
    selector = routes.selector()
    route = selector.choose(wanted)

    if route is None:
        available = selector.routes()
        if not available:
            return {"ok": False, "mode": wanted, "reason": (
                "No usable local network right now. Connect this laptop to "
                "Wi-Fi, or switch on Mobile Hotspot in Windows settings.")}
        names = ", ".join(sorted({r.label for r in available}))
        return {"ok": False, "mode": wanted, "reason": (
            f"{'The laptop hotspot' if wanted == routes.HOTSPOT else 'The Wi-Fi network'}"
            f" is not up, so I cannot make a code for it. Available now: {names}."),
            "routes": [r.as_dict() for r in available]}

    if route.health != routes.READY:
        return {"ok": False, "mode": wanted, "route": route.as_dict(), "reason": (
            f"{route.label} has an address ({route.ipv4}) but nothing is "
            f"listening on {routes.PORT}. Start the phone mic listener first.")}

    pair = get_phone_security().create_pair()
    url = route.url_with(pair["token"])
    result = {
        "ok": True,
        "mode": route.mode,
        "label": route.label,
        "url": url,
        "origin": route.origin,
        "ipv4": route.ipv4,
        "adapter": route.adapter_name,
        "port": routes.PORT,
        "manual_code": pair["manual_code"],
        "expires_at": pair["expires_at"],
        "route": route.as_dict(),
        "alternatives": [r.as_dict() for r in selector.routes() if r.ipv4 != route.ipv4],
        "chrome_flag": pairing.CHROME_FLAG,
        "steps": _steps(route),
    }
    if with_qr:
        result["qr_png"] = pairing._qr(url)
    return result


def offer_both(*, with_qr: bool = True) -> dict[str, Any]:
    """One pairing code, printed for every available network.

    A token is not bound to an address -- it proves the owner is holding this
    laptop's screen, not that the phone is on a particular subnet. So both
    QR codes can carry the SAME token and both stay valid until one of them
    is scanned.

    That is what makes "keep both" real rather than a menu. The owner does
    not have to decide which network they are on before generating a code;
    they scan whichever one their phone can see, and the other dies with it
    because the token is still single-use.
    """
    from reyes_agent.phone_security import get_phone_security

    selector = routes.selector()
    ready = [r for r in selector.routes() if r.health == routes.READY]
    if not ready:
        return {"ok": False, "reason": (
            "No network is serving the phone mic yet. Start the listener, or "
            "connect this laptop to Wi-Fi or switch on Mobile Hotspot.")}

    pair = get_phone_security().create_pair()
    offers = []
    for route in ready:
        entry = {"mode": route.mode, "label": route.label, "ipv4": route.ipv4,
                 "adapter": route.adapter_name, "origin": route.origin,
                 "url": route.url_with(pair["token"]), "steps": _steps(route)}
        if with_qr:
            entry["qr_png"] = pairing._qr(entry["url"])
        offers.append(entry)

    return {"ok": True, "offers": offers, "manual_code": pair["manual_code"],
            "expires_at": pair["expires_at"], "port": routes.PORT,
            "chrome_flag": pairing.CHROME_FLAG,
            "shared_token": ("Both codes carry the same one-time token. Scan "
                             "whichever network your phone can see -- the "
                             "other stops working the moment one is used.")}


def save_both(directory: str | Path = "") -> dict[str, Any]:
    """Write a QR per available network. Both valid until one is scanned."""
    result = offer_both()
    if not result.get("ok"):
        return result
    folder = Path(directory) if directory else (Path.home() / "Desktop")
    folder.mkdir(parents=True, exist_ok=True)
    for entry in result["offers"]:
        target = folder / f"zeno_mic_{entry['mode'].lower()}.png"
        target.write_bytes(base64.b64decode(entry.pop("qr_png").split(",")[-1]))
        entry["path"] = str(target)
    return result


def _steps(route: routes.RemoteMicRoute) -> list[str]:
    """What the owner has to do, in the order they have to do it."""
    common = [
        "On the phone open Chrome and go to chrome://flags",
        'Search "Insecure origins treated as secure"',
        f"Add {route.origin}, set it to Enabled, then relaunch Chrome",
        "Scan the QR code and tap Pair and continue",
        "Allow the microphone when Chrome asks",
    ]
    if route.mode == routes.HOTSPOT:
        return ["On the phone, connect to this laptop's hotspot Wi-Fi", *common]
    return ["Make sure the phone is on the same Wi-Fi as this laptop", *common]


def save_qr(mode: str = "", destination: str | Path = "") -> dict[str, Any]:
    """Write the QR to a file. Returns the same offer plus `path`."""
    result = offer(mode)
    if not result.get("ok"):
        return result
    target = Path(destination) if destination else (
        Path.home() / "Desktop" / f"zeno_mic_qr_{result['mode'].lower()}.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(base64.b64decode(result["qr_png"].split(",")[-1]))
    result["path"] = str(target)
    return result


def say(result: dict[str, Any]) -> str:
    """One spoken sentence about a pairing offer."""
    if not result.get("ok"):
        return result.get("reason", "I could not make a pairing code.")
    where = ("my laptop hotspot" if result["mode"] == routes.HOTSPOT
             else "the Wi-Fi network")
    return (f"Here is the phone microphone code for {where}, at "
            f"{result['ipv4']}. It works once and expires in a few minutes.")


def status() -> dict[str, Any]:
    return {"state": "ONLINE", "networks": routes.status(),
            "token": "one-time, single-use, expires with PAIR_TTL_S",
            "scope": "remote_audio_send only, on either network"}
